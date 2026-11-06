from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from rhythm_helper import app
from rhythm_helper.engine import Action
from rhythm_helper.gui_session import GuiSession
from rhythm_helper.settings import DEFAULTS
from rhythm_helper.vision import Observation


@pytest.mark.parametrize(
    "scenario",
    [
        "toggle",
        "focus",
        "capture_error",
        "interrupt",
        "top_row",
        "console",
        "waiting",
        "no_game",
        "practice",
        "minimized_start",
        "minimized_active",
        "zero_size",
        "permission",
        "cancel_wait",
        "double_toggle",
        "calibrate_then_toggle",
        "gui_stop_after_focus_loss",
        "gui_close_holding",
        "gui_tutorial_with_game",
    ],
)
def test_runtime_releases_owned_keys_without_real_input(monkeypatch, scenario, tmp_path):
    clock = {
        "loop": 0,
        "foreground": 100 if scenario in ("console", "waiting", "cancel_wait") else 1,
    }
    events = []
    held = set()
    states = []
    activations = []
    closed = []
    gui = (
        GuiSession(dict(DEFAULTS), tmp_path / "config.json")
        if scenario.startswith("gui_")
        else None
    )
    if gui:
        gui.command("tutorial" if scenario == "gui_tutorial_with_game" else "start")

    class Controls:
        def __init__(self, bindings):
            self.bindings = bindings

        def poll(self):
            if gui:
                return []
            if scenario == "practice":
                return ["calibrate"] if clock["loop"] == 0 else []
            if scenario == "top_row":
                return []
            if scenario == "double_toggle":
                return ["toggle", "toggle"] if clock["loop"] == 0 else []
            if scenario == "calibrate_then_toggle":
                return ["calibrate", "toggle"] if clock["loop"] == 0 else []
            stop_loop = 2 if scenario == "cancel_wait" else 8
            return ["toggle"] if clock["loop"] in (0, stop_loop) else []

        def close(self):
            closed.append(True)

    class Display:
        def update(self, state, detail="", rect=None):
            states.append((state, detail))

        def pump(self):
            pass

        def close(self):
            pass

    class Output:
        def press(self, key):
            held.add(key)
            events.append((key, True))

        def release(self, key):
            if key in held:
                held.remove(key)
                events.append((key, False))

        def release_all(self):
            for key in list(held):
                self.release(key)

    class StubEngine:
        def __init__(self, *args, **kwargs):
            self.pressed = {}
            self.fired = False

        def step(self, observation, now, **kwargs):
            if not self.fired:
                self.fired = True
                self.pressed[0] = SimpleNamespace(kind="hold", end_at=None, speed=500, not_before=0)
                return [Action("a", True, "hold")]
            return []

        def stop(self):
            self.pressed.clear()

    def sleep(delay):
        clock["loop"] += 1
        if scenario == "gui_close_holding" and clock["loop"] == 6:
            assert held
            gui.close()
        if scenario == "gui_stop_after_focus_loss" and clock["loop"] == 6:
            assert not held
            gui.command("stop")
        if clock["loop"] >= (4 if scenario == "interrupt" else 10):
            raise KeyboardInterrupt

    def grab(region):
        if scenario == "capture_error" and clock["loop"] == 4:
            raise RuntimeError("test capture failure")
        return np.zeros((10, 10, 4), dtype=np.uint8)

    def foreground():
        if scenario in ("focus", "gui_stop_after_focus_loss") and clock["loop"] >= 4:
            return 2
        if scenario == "waiting" and clock["loop"] >= 2:
            return 1
        return clock["foreground"]

    def activate(hwnd):
        activations.append(hwnd)
        if scenario in ("waiting", "cancel_wait"):
            return False
        clock["foreground"] = hwnd
        return True

    def client_rect(hwnd):
        if (scenario == "minimized_start" and clock["loop"] < 3) or (
            scenario == "minimized_active" and clock["loop"] >= 4
        ):
            raise app.WindowUnavailableError("目标窗口已最小化")
        if scenario == "zero_size" and clock["loop"] < 3:
            return (0, 0, 0, 0)
        return (0, 0, 1920, 1080)

    monkeypatch.setattr(app, "enable_dpi_awareness", lambda: None)
    monkeypatch.setattr(app, "StatusDisplay", Display)
    monkeypatch.setattr(app, "GlobalHotkeys", Controls)
    monkeypatch.setattr(app, "beep", lambda state: None)
    monkeypatch.setattr(app, "is_numlock_on", lambda: True)
    monkeypatch.setattr(app, "key_is_down", lambda vk: False)
    monkeypatch.setattr(app, "is_elevated", lambda: False)
    monkeypatch.setattr(app, "window_elevation", lambda hwnd: scenario == "permission")
    monkeypatch.setattr(app, "foreground_window", foreground)
    monkeypatch.setattr(app, "activate_window", activate)
    monkeypatch.setattr(
        app,
        "find_game_windows",
        lambda: (
            [] if scenario in ("no_game", "practice") else [SimpleNamespace(hwnd=1, title="原神")]
        ),
    )
    monkeypatch.setattr(app, "foreground_client_rect", client_rect)
    monkeypatch.setattr(app, "KeyboardOutput", Output)
    monkeypatch.setattr(app, "Engine", StubEngine)
    practice_calls = []
    monkeypatch.setattr(
        app, "practice_calibration", lambda path, ctl, **kw: practice_calls.append(path) or True
    )
    monkeypatch.setattr(
        app, "Detector", lambda *args: SimpleNamespace(detect=lambda f: Observation([], [True] * 6))
    )
    monkeypatch.setattr(app.mss, "mss", lambda: nullcontext(SimpleNamespace(grab=grab)))
    monkeypatch.setattr(app.time, "sleep", sleep)
    monkeypatch.setattr(app.time, "perf_counter", lambda: clock["loop"] * 0.11)
    monkeypatch.setattr(app.cv2, "destroyAllWindows", lambda: None)
    app.runtime(dict(DEFAULTS), tmp_path / "config.json", dry_run=False, gui=gui)
    assert not held
    assert closed == [True]
    if scenario in (
        "top_row",
        "no_game",
        "practice",
        "permission",
        "cancel_wait",
        "double_toggle",
        "calibrate_then_toggle",
        "gui_tutorial_with_game",
    ):
        assert events == []
        assert not any(state == "running" for state, _ in states)
    else:
        assert events[0] == ("a", True)
        assert events[-1] == ("a", False)
        assert len([e for e in events if e[1]]) == len([e for e in events if not e[1]])
        assert any(state == "running" and "原神" in detail for state, detail in states)
    if scenario in ("console", "waiting"):
        assert activations == [1]
        assert any(state == "waiting" for state, _ in states)
    if scenario == "no_game":
        assert any(state == "error" and "未找到原神" in detail for state, detail in states)
    if scenario in ("practice", "gui_tutorial_with_game"):
        assert practice_calls == [tmp_path / "config.json"]
        notices = [payload for kind, payload in gui.drain() if kind == "status"] if gui else states
        assert any(state == "paused" and "练习已保存" in detail for state, detail in notices)
    if scenario == "gui_stop_after_focus_loss":
        assert not activations
    if scenario == "focus":
        assert any(state == "paused" and "切出原神" in detail for state, detail in states)
    if scenario in ("minimized_start", "zero_size", "minimized_active"):
        assert not any(state == "error" for state, _ in states)
    if scenario == "permission":
        assert any(state == "error" and "管理员" in detail for state, detail in states)
    if scenario in ("cancel_wait", "double_toggle", "calibrate_then_toggle"):
        assert any(state == "paused" for state, _ in states)
