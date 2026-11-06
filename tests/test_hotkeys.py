"""Exercise the real worker lifecycle with fake Win32 message queues."""

import ctypes
import queue
import threading
from types import SimpleNamespace

import pytest

from rhythm_helper import hotkeys


class FakeHotkeyApi:
    def __init__(self):
        self.incoming = queue.Queue()
        self.registered = []
        self.active = {}
        self.unregistered = []
        self.posted = []
        self.owner = None
        self.worker_id = 7001
        self.fail_registration = None
        self.fail_combos = set()
        self.fail_unregister = set()
        self.local_error = threading.local()
        self.registration_gate = None
        self.registration_entered = threading.Event()
        self.registration_completed = threading.Event()
        self.queue_created = threading.Event()
        self.message_processed = threading.Event()
        self.message_waiting = threading.Event()
        self.cleanup_completed = threading.Event()

    def set_error(self, code):
        self.local_error.code = code

    def get_error(self):
        return getattr(self.local_error, "code", 0)

    def PeekMessageW(self, _message, hwnd, low, high, remove):
        if (low, high, remove) == (0x312, 0x312, 1):
            assert threading.get_ident() == self.owner
            return 0
        assert (hwnd, low, high, remove) == (None, 0x0400, 0x0400, 0)
        self.owner = threading.get_ident()
        self.queue_created.set()
        return 0

    def GetCurrentThreadId(self):
        assert threading.get_ident() == self.owner
        assert self.queue_created.is_set()
        return self.worker_id

    def RegisterHotKey(self, hwnd, identifier, modifiers, vk):
        assert threading.get_ident() == self.owner
        self.registration_entered.set()
        if self.registration_gate is not None:
            assert self.registration_gate.wait(2)
        combo = (modifiers, vk)
        if (
            identifier == self.fail_registration
            or combo in self.fail_combos
            or combo in self.active.values()
        ):
            self.set_error(1409)
            return 0
        assert identifier not in self.active
        self.active[identifier] = combo
        self.registered.append((hwnd, identifier, modifiers, vk))
        if identifier == 2:
            self.registration_completed.set()
        return 1

    def UnregisterHotKey(self, hwnd, identifier):
        assert threading.get_ident() == self.owner
        assert hwnd is None
        self.unregistered.append(identifier)
        if len(self.unregistered) == len(self.registered):
            self.cleanup_completed.set()
        if identifier in self.fail_unregister:
            self.set_error(1419)
            return 0
        del self.active[identifier]
        return 1

    def GetMessageW(self, pointer, hwnd, low, high):
        assert threading.get_ident() == self.owner
        assert (hwnd, low, high) == (None, 0, 0)
        self.message_waiting.set()
        incoming = self.incoming.get(timeout=2)
        if incoming == "error":
            self.set_error(5)
            return -1
        if incoming == "raise":
            raise OSError("message queue failed")
        if incoming == "quit":
            return 0
        if incoming == "barrier":
            # The next GetMessage call proves the previous event was enqueued.
            ctypes.cast(pointer, ctypes.POINTER(hotkeys._MSG)).contents.message = 0
            self.message_processed.set()
            return 1
        message = ctypes.cast(pointer, ctypes.POINTER(hotkeys._MSG)).contents
        message.message, message.wParam = incoming
        return 1

    def PostThreadMessageW(self, thread_id, message, wparam, lparam):
        assert self.queue_created.is_set()
        self.posted.append((thread_id, message, wparam, lparam))
        if message == hotkeys._WM_REBIND:
            assert (thread_id, wparam, lparam) == (self.worker_id, 0, 0)
            self.incoming.put((message, 0))
            return 1
        assert (thread_id, message, wparam, lparam) == (self.worker_id, 0x12, 0, 0)
        self.incoming.put("quit")
        return 1

    def send_events(self, *events):
        self.message_processed.clear()
        for event in events:
            self.incoming.put(event)
        self.incoming.put("barrier")
        assert self.message_processed.wait(1)


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeHotkeyApi()
    monkeypatch.setattr(hotkeys, "_load_api", lambda: (api, api))
    monkeypatch.setattr(ctypes, "set_last_error", api.set_error, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", api.get_error, raising=False)
    return api


def test_message_abi_has_pointer_sized_parameters():
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(hotkeys._MSG) == (48 if is_64_bit else 32)
    assert hotkeys._MSG.wParam.offset == (16 if is_64_bit else 8)
    assert hotkeys._MSG.lParam.offset == (24 if is_64_bit else 12)


def test_constructor_registers_numpad9_and_f6_on_dedicated_thread(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        assert fake_api.registration_completed.is_set()
        assert fake_api.owner != threading.get_ident()
        assert fake_api.registered == [(None, 1, 0x4000, 0x69), (None, 2, 0x4000, 0x75)]
        assert service.poll() == []
    finally:
        service.close()
    assert fake_api.unregistered == [2, 1]
    assert fake_api.posted == [(7001, 0x12, 0, 0)]
    assert not service._thread.is_alive()
    service.close()
    assert len(fake_api.posted) == 1
    assert service.poll() == []


def test_poll_preserves_two_separate_toggle_presses(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        fake_api.send_events((0x312, 1), (0x312, 1))
        assert service.poll() == ["toggle", "toggle"]
        assert service.poll() == []
    finally:
        service.close()


def test_poll_preserves_mixed_command_order_and_ignores_unknown_messages(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        fake_api.send_events(
            (0x312, 1), (0x312, 2), (0x312, 999), (0x312, 1), (0x401, 1), (0x312, 2)
        )
        assert service.poll() == ["toggle", "calibrate", "toggle", "calibrate"]
        assert service.poll() == []
    finally:
        service.close()


@pytest.mark.parametrize("failed_id, expected_cleanup", [(1, []), (2, [1])])
def test_registration_conflict_reports_old_instance_and_cleans_partial_registration(
    fake_api, failed_id, expected_cleanup
):
    fake_api.fail_registration = failed_id
    with pytest.raises(RuntimeError, match="已被占用.*关闭旧版"):
        hotkeys.GlobalHotkeys()
    assert fake_api.unregistered == expected_cleanup


@pytest.mark.parametrize("failure", ["error", "raise", "quit"])
def test_background_failure_is_reported_by_poll_and_unregisters(fake_api, failure):
    service = hotkeys.GlobalHotkeys()
    try:
        fake_api.incoming.put(failure)
        assert service._finished.wait(1)
        with pytest.raises(RuntimeError, match="全局热键不可用"):
            service.poll()
        assert fake_api.unregistered == [2, 1]
    finally:
        service.close()


def test_cleanup_attempts_all_registrations_even_if_one_fails(fake_api):
    service = hotkeys.GlobalHotkeys()
    fake_api.fail_unregister.add(2)
    with pytest.raises(RuntimeError, match="注销失败"):
        service.close()
    assert fake_api.unregistered == [2, 1]
    assert not service._thread.is_alive()
    service.close()


def test_startup_timeout_stops_late_registration_and_cleans_it(fake_api, monkeypatch):
    gate = threading.Event()
    fake_api.registration_gate = gate
    monkeypatch.setattr(hotkeys, "_STARTUP_TIMEOUT", 0.02)
    monkeypatch.setattr(hotkeys, "_SHUTDOWN_TIMEOUT", 0.02)
    try:
        with pytest.raises(RuntimeError, match="启动超时"):
            hotkeys.GlobalHotkeys()
    finally:
        # An in-progress native call cannot be killed; when it returns, the
        # worker must unregister its result and must not register the next key.
        gate.set()
    assert fake_api.cleanup_completed.wait(1)
    assert fake_api.registered == [(None, 1, 0x4000, 0x69)]
    assert fake_api.unregistered == [1]


def test_native_thread_start_failure_has_clear_error(fake_api, monkeypatch):
    def fail_start(_self):
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="无法启动全局热键线程"):
        hotkeys.GlobalHotkeys()
    assert fake_api.registered == []


def test_close_is_bounded_when_quit_post_fails_and_can_be_retried(fake_api, monkeypatch):
    service = hotkeys.GlobalHotkeys()
    assert fake_api.message_waiting.wait(1)
    monkeypatch.setattr(hotkeys, "_SHUTDOWN_TIMEOUT", 0.02)
    monkeypatch.setattr(fake_api, "PostThreadMessageW", lambda *_args: 0)
    try:
        with pytest.raises(RuntimeError, match="未及时停止"):
            service.close()
    finally:
        fake_api.incoming.put("quit")
        assert service._finished.wait(1)
        service.close()
    assert fake_api.unregistered == [2, 1]


def test_nonwindows_construction_is_rejected(monkeypatch):
    monkeypatch.setattr(hotkeys, "os", SimpleNamespace(name="posix"))
    with pytest.raises(RuntimeError, match="Windows"):
        hotkeys.GlobalHotkeys()


def test_custom_shortcuts_register_with_norepeat_and_modifiers(fake_api):
    service = hotkeys.GlobalHotkeys({"toggle": "Alt+Ctrl+P", "calibrate": "Shift+F8"})
    try:
        assert fake_api.active == {1: (0x4003, 0x50), 2: (0x4004, 0x77)}
    finally:
        service.close()


def test_swapping_actions_keeps_physical_registrations_and_drops_old_commands(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        fake_api.send_events((0x312, 1))
        service.rebind({"toggle": "F6", "calibrate": "NumPad9"})
        assert service.poll() == []
        assert not fake_api.unregistered
        assert len(fake_api.registered) == 2
        fake_api.send_events((0x312, 1), (0x312, 2))
        assert service.poll() == ["calibrate", "toggle"]
    finally:
        service.close()


def test_conflicting_second_key_reverts_staged_key_and_preserves_old_service(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        fake_api.fail_combos.add((0x4002, 0x50))
        with pytest.raises(RuntimeError, match="Ctrl\\+P.*占用"):
            service.rebind({"toggle": "F8", "calibrate": "Ctrl+P"})
        assert fake_api.active == {1: (0x4000, 0x69), 2: (0x4000, 0x75)}
        fake_api.send_events((0x312, 1), (0x312, 2))
        assert service.poll() == ["toggle", "calibrate"]
        fake_api.fail_combos.clear()
        service.rebind({"toggle": "F8", "calibrate": "Ctrl+P"})
        assert fake_api.active == {3: (0x4000, 0x77), 4: (0x4002, 0x50)}
        fake_api.send_events((0x312, 1), (0x312, 3), (0x312, 4))
        assert service.poll() == ["toggle", "calibrate"]
    finally:
        service.close()
    assert not fake_api.active


def test_invalid_or_identical_map_never_posts_change(fake_api):
    service = hotkeys.GlobalHotkeys()
    try:
        with pytest.raises(ValueError):
            service.rebind({"toggle": "F6", "calibrate": "f6"})
        service.rebind({"toggle": "kp_9", "calibrate": "f6"})
        assert not fake_api.posted
    finally:
        service.close()
    with pytest.raises(RuntimeError, match="关闭"):
        service.rebind({"toggle": "F8", "calibrate": "F6"})


def test_fatal_rollback_failure_stops_worker_and_poll_keeps_reporting_failure(fake_api):
    service = hotkeys.GlobalHotkeys()
    fake_api.fail_combos.add((0x4002, 0x50))
    fake_api.fail_unregister.add(3)
    with pytest.raises(RuntimeError):
        service.rebind({"toggle": "F8", "calibrate": "Ctrl+P"})
    assert service._finished.wait(1)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="全局热键不可用"):
            service.poll()
    with pytest.raises(RuntimeError, match="注销失败"):
        service.close()
    assert not service._thread.is_alive()
    assert {1, 2, 3} <= set(fake_api.unregistered)


def test_timeout_fails_closed_and_worker_cleans_after_native_call_returns(fake_api, monkeypatch):
    service = hotkeys.GlobalHotkeys()
    gate = threading.Event()
    fake_api.registration_gate = gate
    monkeypatch.setattr(hotkeys, "_REBIND_TIMEOUT", 0.03)
    try:
        with pytest.raises(RuntimeError, match="超时"):
            service.rebind({"toggle": "F8", "calibrate": "Ctrl+P"})
        with pytest.raises(RuntimeError, match="超时"):
            service.poll()
    finally:
        gate.set()
        service.close()
    assert not fake_api.active


def test_close_and_rebind_release_all_combinations_on_owner_thread(fake_api):
    service = hotkeys.GlobalHotkeys()
    gate = threading.Event()
    fake_api.registration_gate = gate
    fake_api.registration_entered.clear()
    errors = []

    def change():
        try:
            service.rebind({"toggle": "Ctrl+F8", "calibrate": "Ctrl+P"})
        except BaseException as error:
            errors.append(error)

    caller = threading.Thread(target=change)
    caller.start()
    assert fake_api.registration_entered.wait(1)
    closer = threading.Thread(target=service.close)
    closer.start()
    gate.set()
    for thread in (caller, closer):
        thread.join(2)
        assert not thread.is_alive()
    assert not errors
    assert not service._thread.is_alive()
    assert not fake_api.active


def test_failed_change_notification_keeps_existing_hotkeys(fake_api, monkeypatch):
    service = hotkeys.GlobalHotkeys()
    original_post = fake_api.PostThreadMessageW

    def post(thread_id, message, wparam, lparam):
        if message == hotkeys._WM_REBIND:
            return 0
        return original_post(thread_id, message, wparam, lparam)

    monkeypatch.setattr(fake_api, "PostThreadMessageW", post)
    try:
        with pytest.raises(RuntimeError, match="通知热键线程"):
            service.rebind({"toggle": "F7", "calibrate": "F8"})
        fake_api.send_events((0x312, 1))
        assert service.poll() == ["toggle"]
    finally:
        service.close()
