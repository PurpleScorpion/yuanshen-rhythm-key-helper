from __future__ import annotations

import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

from .keybinds import DEFAULT_HOTKEYS, validate

DEFAULTS = {
    "hotkeys": DEFAULT_HOTKEYS.copy(),
    "keys": ["a", "s", "d", "j", "k", "l"],
    "lane_x": [419 / 1920, 635 / 1920, 852 / 1920, 1068 / 1920, 1285 / 1920, 1501 / 1920],
    "hit_y": 921 / 1080,
    "input_lead_ms": 8,
    "tap_ms": 28,
    "release_grace_ms": 65,
    "max_hold_seconds": 30,
    "target_fps": 120,
}


def load_config(path: Path) -> dict:
    settings = dict(DEFAULTS)
    if path.exists():
        contents = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(contents, dict):
            raise ValueError("配置文件必须是 JSON 对象。")
        settings.update(contents)
    validate_config(settings)
    return settings


def validate_config(settings: dict) -> None:
    settings["hotkeys"] = validate(settings.get("hotkeys", DEFAULT_HOTKEYS))
    keys = settings["keys"]
    if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
        raise ValueError("keys 必须是六个小写按键名的数组。")
    if sorted(keys) != sorted(DEFAULTS["keys"]):
        raise ValueError("keys 必须包含 A/S/D/J/K/L 的六个小写键名，各一次。")
    xs = settings["lane_x"]
    if (
        not isinstance(xs, list)
        or len(xs) != 6
        or any(not isinstance(x, (int, float)) or not 0.03 < x < 0.97 for x in xs)
        or any(b - a < 0.025 for a, b in zip(xs, xs[1:], strict=False))
    ):
        raise ValueError("lane_x 必须是从左到右递增的六个相对坐标，请重新校准。")
    bounds = {
        "hit_y": (0.2, 0.95),
        "input_lead_ms": (-50, 100),
        "tap_ms": (5, 100),
        "release_grace_ms": (0, 250),
        "max_hold_seconds": (1, 180),
        "target_fps": (30, 240),
    }
    for name, (low, high) in bounds.items():
        value = settings[name]
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"{name} 必须在 {low} 到 {high} 之间。")


def save_config(path: Path, settings: dict) -> None:
    validate_config(settings)
    content = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
    with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def geometry(settings: dict, width: int, height: int) -> tuple[list[float], float, float]:
    xs = [x * width for x in settings["lane_x"]]
    scale = (xs[-1] - xs[0]) / (1501 - 419)
    return xs, settings["hit_y"] * height, scale
