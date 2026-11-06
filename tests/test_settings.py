import json

import pytest

from rhythm_helper.settings import DEFAULTS, load_config, save_config, validate_config


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("lane_x", None),
        ("lane_x", [0.1] * 6),
        ("keys", None),
        ("hit_y", 0.99),
        ("input_lead_ms", float("nan")),
    ],
)
def test_rejects_invalid_values(key, value):
    with pytest.raises(ValueError):
        validate_config({**DEFAULTS, key: value})


def test_invalid_calibration_does_not_overwrite_valid_config(tmp_path):
    path = tmp_path / "config.json"
    save_config(path, DEFAULTS)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        save_config(path, {**DEFAULTS, "hit_y": 0.99})
    assert path.read_bytes() == original
    assert load_config(path) == DEFAULTS


def test_config_requires_an_object(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_config(path)
