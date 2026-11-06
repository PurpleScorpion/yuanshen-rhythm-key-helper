from threading import Event, Thread
from types import SimpleNamespace

from rhythm_helper.gui_session import GuiSession


def test_stop_and_close_disarm_new_presses_without_waiting_for_capture():
    session = GuiSession({}, None)
    pressed = []
    output = SimpleNamespace(press=pressed.append)
    assert session.press(output, "a")
    session.command("stop")
    assert not session.press(output, "s")
    assert session.poll() == ["stop"]
    session.close()
    session.command("start")
    assert session.poll() == []
    assert not session.press(output, "d")
    assert pressed == ["a"]


def test_closing_before_gui_claims_picker_releases_worker():
    session = GuiSession({}, None)
    ready = Event()
    requested = []

    def publish(kind, payload):
        requested.append(payload)
        ready.set()

    session.publish = publish
    result = []
    opened = []
    worker = Thread(
        target=lambda: result.append(
            session.open_picker(
                lambda ctl, parent: opened.append(parent), SimpleNamespace(poll=lambda: [])
            )
        )
    )
    worker.start()
    try:
        assert ready.wait(1)
    finally:
        session.close()
        worker.join(1)
    assert not worker.is_alive()
    assert result == [False]
    requested[0]()
    assert opened == []


def test_editing_captures_registered_keys_instead_of_playing():
    session = GuiSession({}, None)
    bindings = {"toggle": "F8", "calibrate": "F6"}
    session.begin_hotkey_edit()
    assert session.route(["toggle"], bindings) == ["edit_begin"]
    assert session.drain() == [("hotkey_capture", "F8")]
    assert not session.press(None, "a")
    session.set_hotkeys(bindings)
    assert session.route([], bindings) == [("hotkeys", bindings)]
    session.end_hotkey_edit()
    assert session.route(["calibrate"], bindings) == ["edit_end"]
    assert session.route(["toggle"], bindings) == ["toggle"]
