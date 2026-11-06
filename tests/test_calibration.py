from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rhythm_helper import app, calibration_ui
from rhythm_helper.settings import DEFAULTS, load_config, save_config


def test_game_window_freezes_before_prompt_and_only_writes_on_valid_save(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    settings = {**DEFAULTS, "input_lead_ms": 13}
    save_config(path, settings)
    original = path.read_bytes()
    rect = (-400, 110, 1000, 600)
    captures = []

    def grab(region):
        captures.append(region)
        return np.zeros((600, 1000, 4), dtype=np.uint8)

    def choose(frame, current, save, **options):
        assert frame.shape == (600, 1000, 3)
        assert captures == [{"left": -400, "top": 110, "width": 1000, "height": 600}]
        assert options["screen_rect"] == rect and not options["demo"]
        assert save([(750, 510), (250, 510)])
        assert path.read_bytes() == original
        assert save([(250, 510), (750, 510)]) is None
        return True

    monkeypatch.setattr(calibration_ui, "choose_calibration", choose)
    assert app.calibrate(SimpleNamespace(grab=grab), rect, settings, path)
    assert load_config(path) == settings
    assert settings["lane_x"] == pytest.approx([0.25, 0.35, 0.45, 0.55, 0.65, 0.75])
    assert settings["hit_y"] == 0.85 and settings["input_lead_ms"] == 13


@pytest.mark.parametrize("confirm", [False, True])
def test_practice_keeps_game_settings_separate(tmp_path, monkeypatch, confirm):
    path = tmp_path / "config.json"
    path.write_bytes(b"untouched real settings")

    def choose(frame, current, save, **options):
        assert options["demo"] and options["screen_rect"] is None
        if confirm:
            assert save([(279, 650), (1001, 650)])
            assert not (tmp_path / "calibration-practice.json").exists()
            assert save([(279, 614), (1001, 614)]) is None
        return confirm

    monkeypatch.setattr(calibration_ui, "choose_calibration", choose)
    assert app.practice_calibration(path) == confirm
    assert path.read_bytes() == b"untouched real settings"
    practice = Path(tmp_path, "calibration-practice.json")
    assert practice.exists() == confirm
    if confirm:
        assert load_config(practice)["hit_y"] == pytest.approx(614 / 720)
