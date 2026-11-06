"""Test Win32 input packets without loading User32 or sending real keys."""

import ctypes
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from rhythm_helper import windows_io


@dataclass
class FakeUser32:
    events: list[tuple[int, int, int, int, int, int]] = field(default_factory=list)
    failures: set[tuple[int, int]] = field(default_factory=set)

    def SendInput(self, count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(windows_io._INPUT)).contents
        packet = (count, size, event.type, event.ki.wVk, event.ki.wScan, event.ki.dwFlags)
        self.events.append(packet)
        return 0 if packet[-2:] in self.failures else count


@pytest.fixture
def keyboard(monkeypatch):
    api = FakeUser32()
    # Patch the loader itself, so these tests cannot reach a native input API.
    monkeypatch.setattr(windows_io, "_api", lambda: api)
    monkeypatch.setattr(ctypes, "set_last_error", lambda code: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    return windows_io.KeyboardOutput(), api


def test_input_abi_includes_full_union():
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(windows_io._INPUT) == (40 if is_64_bit else 28)
    assert ctypes.sizeof(windows_io._KEYBDINPUT) == (24 if is_64_bit else 16)
    assert windows_io._INPUT.data.offset == (8 if is_64_bit else 4)
    assert ctypes.sizeof(windows_io._MOUSEINPUT) == (32 if is_64_bit else 24)


@pytest.mark.parametrize(
    ("key", "scan"),
    [("a", 0x1E), ("s", 0x1F), ("d", 0x20), ("j", 0x24), ("k", 0x25), ("l", 0x26)],
)
def test_scan_code_down_and_up_packets(keyboard, key, scan):
    output, api = keyboard
    output.press(key.upper())
    assert output.held_keys == frozenset((key,))
    output.release(key)
    size = ctypes.sizeof(windows_io._INPUT)
    assert api.events == [(1, size, 1, 0, scan, 0x8), (1, size, 1, 0, scan, 0xA)]
    assert not output.held_keys


def test_chord_keeps_other_keys_held(keyboard):
    output, api = keyboard
    output.press("a")
    output.press("k")
    output.press("l")
    assert output.held_keys == frozenset(("a", "k", "l"))
    output.release("k")
    assert output.held_keys == frozenset(("a", "l"))
    assert [(event[4], event[5]) for event in api.events] == [
        (0x1E, 0x8),
        (0x25, 0x8),
        (0x26, 0x8),
        (0x25, 0xA),
    ]


def test_repeated_calls_and_unowned_release_are_noops(keyboard):
    output, api = keyboard
    output.release("a")
    output.release_all()
    assert not api.events
    output.press("A")
    output.press("a")
    output.release("a")
    output.release("A")
    output.release_all()
    assert len(api.events) == 2
    assert not output.held_keys


def test_release_all_attempts_other_keys_and_retains_failed_key(keyboard):
    output, api = keyboard
    output.press("a")
    output.press("s")
    api.failures.add((0x1E, 0xA))
    with pytest.raises(OSError, match="a"):
        output.release_all()
    assert [(event[4], event[5]) for event in api.events[2:]] == [
        (0x1E, 0xA),
        (0x1F, 0xA),
    ]
    assert output.held_keys == frozenset(("a",))
    api.failures.clear()
    output.release_all()
    assert api.events[-1][4:] == (0x1E, 0xA)
    assert not output.held_keys


def test_failed_press_does_not_claim_key(keyboard):
    output, api = keyboard
    api.failures.add((0x20, 0x8))
    with pytest.raises(OSError, match="SendInput"):
        output.press("d")
    assert not output.held_keys
    output.release_all()
    assert len(api.events) == 1


def test_unsupported_key_is_rejected_without_output(keyboard):
    output, api = keyboard
    with pytest.raises(ValueError):
        output.press("z")
    assert not api.events


@dataclass
class FakeWindow:
    hwnd: int
    pid: int
    title: str
    path: str
    class_name: str = "UnityWndClass"
    visible: bool = True
    minimized: bool = False
    open_error: int = 0
    query_error: int = 0


class FakeDesktop:
    def __init__(self):
        self.windows: dict[int, FakeWindow] = {}
        self.last_error = 0
        self.opened: list[tuple[int, bool, int]] = []
        self.closed: list[int] = []
        self.actions: list[tuple] = []
        self.foreground = 0
        self.allow_activation = True
        self.numlock = 0

    def add(self, *windows):
        self.windows.update((window.hwnd, window) for window in windows)

    def EnumWindows(self, callback, lparam):
        for hwnd in self.windows:
            assert callback(hwnd, lparam)
        return 1

    def IsWindowVisible(self, hwnd):
        return self.windows[hwnd].visible

    def IsWindow(self, hwnd):
        return hwnd in self.windows

    def IsIconic(self, hwnd):
        return self.windows[hwnd].minimized

    def GetWindowThreadProcessId(self, hwnd, pid_pointer):
        ctypes.cast(pid_pointer, ctypes.POINTER(windows_io._DWORD))[0] = self.windows[hwnd].pid
        return 123

    def GetWindowTextLengthW(self, hwnd):
        return len(self.windows[hwnd].title)

    def GetWindowTextW(self, hwnd, buffer, _size):
        buffer.value = self.windows[hwnd].title
        return len(buffer.value)

    def GetClassNameW(self, hwnd, buffer, _size):
        buffer.value = self.windows[hwnd].class_name
        return len(buffer.value)

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        window = next(window for window in self.windows.values() if window.pid == pid)
        if window.open_error:
            self.last_error = window.open_error
            return 0
        # Deliberately exceed 32 bits to catch accidental handle truncation.
        return 0x100000000 + pid

    def QueryFullProcessImageNameW(self, handle, flags, buffer, size_pointer):
        assert flags == 0
        pid = handle - 0x100000000
        window = next(window for window in self.windows.values() if window.pid == pid)
        if window.query_error:
            self.last_error = window.query_error
            return 0
        buffer.value = window.path
        ctypes.cast(size_pointer, ctypes.POINTER(windows_io._DWORD))[0] = len(window.path)
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    def ShowWindow(self, hwnd, command):
        self.actions.append(("show", hwnd, command))
        self.windows[hwnd].minimized = False
        return 1

    def SetForegroundWindow(self, hwnd):
        self.actions.append(("foreground", hwnd))
        if self.allow_activation:
            self.foreground = hwnd
        return self.allow_activation

    def GetForegroundWindow(self):
        return self.foreground

    def GetKeyState(self, vk):
        assert vk == 0x90
        return self.numlock


@pytest.fixture
def desktop(monkeypatch):
    api = FakeDesktop()
    monkeypatch.setattr(windows_io, "_api", lambda: api)
    monkeypatch.setattr(windows_io, "_kernel_api", lambda: api)
    monkeypatch.setattr(windows_io.os, "getpid", lambda: 4242)
    monkeypatch.setattr(
        ctypes, "set_last_error", lambda code: setattr(api, "last_error", code), raising=False
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: api.last_error, raising=False)
    return api


def test_game_discovery_uses_exact_exe_whitelist_and_excludes_self(desktop):
    desktop.add(
        FakeWindow(11, 101, "原神", r"C:\Games\YuAnShEn.ExE", minimized=True),
        FakeWindow(12, 102, "Genshin Impact", r"C:\Games\GenshinImpact.exe"),
        FakeWindow(13, 103, "原神", r"C:\Apps\python.exe", "ConsoleWindowClass"),
        FakeWindow(14, 104, "原神", r"C:\Apps\python.exe"),
        FakeWindow(15, 105, "原神", r"C:\Games\Yuanshen.exe.bak"),
        FakeWindow(16, 106, "原神", r"C:\Games\Yuanshen.exe", visible=False),
        FakeWindow(17, 4242, "原神", r"C:\Games\Yuanshen.exe"),
        FakeWindow(18, 108, "原神 - helper.exe", r"C:\Apps\helper.exe"),
    )
    assert windows_io.find_game_windows() == [
        windows_io.GameWindow(11, "原神", "YuAnShEn.ExE"),
        windows_io.GameWindow(12, "Genshin Impact", "GenshinImpact.exe"),
    ]
    assert all(access == 0x1000 and not inherit for access, inherit, _pid in desktop.opened)
    assert {pid for _access, _inherit, pid in desktop.opened} == {101, 102, 103, 104, 105, 108}
    assert desktop.closed == [0x100000000 + pid for _access, _inherit, pid in desktop.opened]
    assert not desktop.actions


@pytest.mark.parametrize("stage", ["open_error", "query_error"])
@pytest.mark.parametrize("error_code", [5, 1314])
def test_permission_fallback_requires_exact_title_and_unity_class(desktop, stage, error_code):
    error = {stage: error_code}
    desktop.add(
        FakeWindow(11, 101, "原神", "", **error),
        FakeWindow(12, 102, "Genshin Impact", "", **error),
        FakeWindow(13, 103, "原神", "", "ConsoleWindowClass", **error),
        FakeWindow(14, 104, "原神 - helper", "", **error),
        FakeWindow(15, 105, "genshin impact", "", **error),
    )
    assert windows_io.find_game_windows() == [
        windows_io.GameWindow(11, "原神", ""),
        windows_io.GameWindow(12, "Genshin Impact", ""),
    ]
    assert len(desktop.closed) == (5 if stage == "query_error" else 0)


@pytest.mark.parametrize("stage", ["open_error", "query_error"])
def test_nonpermission_process_failure_does_not_enable_title_fallback(desktop, stage):
    desktop.add(FakeWindow(11, 101, "原神", "", **{stage: 87}))
    assert windows_io.find_game_windows() == []
    assert len(desktop.closed) == (1 if stage == "query_error" else 0)


def test_process_handle_is_closed_even_when_query_raises(desktop, monkeypatch):
    desktop.add(FakeWindow(11, 101, "原神", r"C:\Games\Yuanshen.exe"))

    def fail_query(*_args):
        raise OSError("query failed")

    monkeypatch.setattr(desktop, "QueryFullProcessImageNameW", fail_query)
    with pytest.raises(OSError, match="query failed"):
        windows_io._process_name(101)
    assert desktop.closed == [0x100000000 + 101]


def test_activation_restores_minimized_game_then_checks_actual_focus(desktop):
    desktop.add(FakeWindow(11, 101, "原神", "", minimized=True))
    assert windows_io.activate_window(11)
    assert desktop.actions == [("show", 11, 9), ("foreground", 11)]
    assert not desktop.windows[11].minimized


def test_activation_denial_returns_false_without_retry(desktop):
    desktop.add(FakeWindow(11, 101, "原神", ""))
    desktop.allow_activation = False
    assert not windows_io.activate_window(11)
    assert desktop.actions == [("foreground", 11)]
    assert not windows_io.activate_window(99)
    assert len(desktop.actions) == 1


@pytest.mark.parametrize(
    "state, expected", [(0, False), (1, True), (0x8000, False), (0x8001, True)]
)
def test_numlock_uses_toggle_bit(desktop, state, expected):
    desktop.numlock = state
    assert windows_io.is_numlock_on() is expected


def test_new_window_helpers_have_nonwindows_guards(monkeypatch):
    monkeypatch.setattr(windows_io, "os", SimpleNamespace(name="posix"))
    with pytest.raises(RuntimeError, match="Windows"):
        windows_io.find_game_windows()
    with pytest.raises(RuntimeError, match="Windows"):
        windows_io.activate_window(11)
    with pytest.raises(RuntimeError, match="Windows"):
        windows_io.is_numlock_on()
    with pytest.raises(RuntimeError, match="Windows"):
        windows_io.is_elevated()
    with pytest.raises(RuntimeError, match="Windows"):
        windows_io.window_elevation(11)


class FakeTokens:
    def __init__(self):
        self.elevated = 0
        self.failure = ""
        self.opened: list[tuple[int, int]] = []
        self.queries: list[int] = []

    def OpenProcessToken(self, process, access, pointer):
        self.opened.append((process, access))
        assert access == 0x0008  # TOKEN_QUERY, never privilege-adjustment access.
        if self.failure == "open":
            return 0
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = 0x200000000 + abs(process)
        return 1

    def GetTokenInformation(self, token, kind, information, size, returned):
        self.queries.append(token)
        assert kind == 20
        assert size == ctypes.sizeof(windows_io._TOKEN_ELEVATION) == 4
        if self.failure == "query":
            return 0
        if self.failure == "exception":
            raise OSError("token query interrupted")
        ctypes.cast(
            information, ctypes.POINTER(windows_io._TOKEN_ELEVATION)
        ).contents.TokenIsElevated = self.elevated
        ctypes.cast(returned, ctypes.POINTER(windows_io._DWORD))[0] = (
            0 if self.failure == "length" else size
        )
        return 1


@pytest.fixture
def tokens(desktop, monkeypatch):
    api = FakeTokens()
    desktop.add(FakeWindow(11, 101, "原神", r"C:\Games\Yuanshen.exe"))
    monkeypatch.setattr(windows_io, "_security_api", lambda: api)
    monkeypatch.setattr(desktop, "GetCurrentProcess", lambda: -1, raising=False)
    return api, desktop


@pytest.mark.parametrize("value, expected", [(0, False), (1, True)])
def test_current_elevation_queries_only_token_and_never_closes_pseudo_handle(
    tokens, value, expected
):
    token_api, desktop = tokens
    token_api.elevated = value
    assert windows_io.is_elevated() is expected
    assert token_api.opened == [(-1, 0x0008)]
    assert not desktop.opened  # No extra OpenProcess needed for the current process.
    assert desktop.closed == [0x200000001]
    assert not desktop.actions


@pytest.mark.parametrize("value, expected", [(0, False), (1, True)])
def test_window_elevation_closes_token_then_process_using_query_only_access(
    tokens, value, expected
):
    token_api, desktop = tokens
    token_api.elevated = value
    assert windows_io.window_elevation(11) is expected
    assert desktop.opened == [(0x1000, False, 101)]
    assert token_api.opened == [(0x100000065, 0x0008)]
    assert desktop.closed == [0x300000065, 0x100000065]
    assert not desktop.actions


@pytest.mark.parametrize("hwnd", [0, 99])
def test_missing_window_elevation_is_unknown_without_opening_handles(tokens, hwnd):
    token_api, desktop = tokens
    assert windows_io.window_elevation(hwnd) is None
    assert not desktop.opened
    assert not token_api.opened
    assert not desktop.closed


def test_disappearing_window_elevation_is_unknown(tokens, monkeypatch):
    token_api, desktop = tokens
    monkeypatch.setattr(desktop, "GetWindowThreadProcessId", lambda *_args: 0)
    assert windows_io.window_elevation(11) is None
    assert not desktop.opened
    assert not token_api.opened


@pytest.mark.parametrize("error", [5, 87])
def test_inaccessible_or_exited_process_elevation_is_unknown(tokens, error):
    token_api, desktop = tokens
    desktop.windows[11].open_error = error
    assert windows_io.window_elevation(11) is None
    assert not token_api.opened
    assert not desktop.closed


@pytest.mark.parametrize("failure", ["open", "query", "exception", "length"])
def test_failed_target_token_query_is_unknown_and_closes_every_open_handle(tokens, failure):
    token_api, desktop = tokens
    token_api.failure = failure
    assert windows_io.window_elevation(11) is None
    expected = [0x100000065] if failure == "open" else [0x300000065, 0x100000065]
    assert desktop.closed == expected


@pytest.mark.parametrize("failure", ["open", "query", "exception", "length"])
def test_failed_current_token_query_raises_instead_of_claiming_unelevated(tokens, failure):
    token_api, desktop = tokens
    token_api.failure = failure
    with pytest.raises(OSError):
        windows_io.is_elevated()
    assert desktop.closed == ([] if failure == "open" else [0x200000001])


def test_minimized_window_is_temporarily_unavailable(desktop):
    desktop.add(FakeWindow(11, 101, "原神", "", minimized=True))
    with pytest.raises(windows_io.WindowUnavailableError, match="最小化"):
        windows_io.foreground_client_rect(11)
    assert not desktop.actions


def test_invalid_window_still_raises_regular_value_error(desktop):
    with pytest.raises(ValueError) as result:
        windows_io.foreground_client_rect(99)
    assert not isinstance(result.value, windows_io.WindowUnavailableError)


@pytest.mark.parametrize("width, height", [(0, 1080), (1920, 0), (0, 0)])
def test_empty_client_area_is_temporarily_unavailable(desktop, monkeypatch, width, height):
    desktop.add(FakeWindow(11, 101, "原神", ""))

    def get_rect(_hwnd, pointer):
        rect = ctypes.cast(pointer, ctypes.POINTER(windows_io._RECT)).contents
        rect.right, rect.bottom = width, height
        return 1

    monkeypatch.setattr(desktop, "GetClientRect", get_rect, raising=False)
    with pytest.raises(windows_io.WindowUnavailableError, match="画面区域"):
        windows_io.foreground_client_rect(11)


@pytest.mark.parametrize("conversion_result", [0, 1])
def test_minimizing_during_coordinate_conversion_is_temporarily_unavailable(
    desktop, monkeypatch, conversion_result
):
    desktop.add(FakeWindow(11, 101, "原神", ""))

    def get_rect(_hwnd, pointer):
        rect = ctypes.cast(pointer, ctypes.POINTER(windows_io._RECT)).contents
        rect.right, rect.bottom = 1920, 1080
        return 1

    def client_to_screen(hwnd, _pointer):
        desktop.windows[hwnd].minimized = True
        return conversion_result

    monkeypatch.setattr(desktop, "GetClientRect", get_rect, raising=False)
    monkeypatch.setattr(desktop, "ClientToScreen", client_to_screen, raising=False)
    with pytest.raises(windows_io.WindowUnavailableError, match="正在最小化"):
        windows_io.foreground_client_rect(11)


def test_minimizing_during_client_query_is_temporarily_unavailable(desktop, monkeypatch):
    desktop.add(FakeWindow(11, 101, "原神", ""))

    def get_rect(hwnd, _pointer):
        desktop.windows[hwnd].minimized = True
        return 0

    monkeypatch.setattr(desktop, "GetClientRect", get_rect, raising=False)
    with pytest.raises(windows_io.WindowUnavailableError, match="正在最小化"):
        windows_io.foreground_client_rect(11)


def test_window_closing_during_client_query_is_regular_value_error(desktop, monkeypatch):
    desktop.add(FakeWindow(11, 101, "原神", ""))

    def get_rect(hwnd, _pointer):
        del desktop.windows[hwnd]
        return 0

    monkeypatch.setattr(desktop, "GetClientRect", get_rect, raising=False)
    with pytest.raises(ValueError) as result:
        windows_io.foreground_client_rect(11)
    assert not isinstance(result.value, windows_io.WindowUnavailableError)
