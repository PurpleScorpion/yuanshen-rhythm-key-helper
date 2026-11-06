"""Validate, display and capture the two Windows global keyboard shortcuts."""

import ctypes
import sys
from collections.abc import Mapping
from string import ascii_uppercase, digits

DEFAULT_HOTKEYS = {"toggle": "NumPad9", "calibrate": "F6"}
_MODIFIERS = {"Ctrl": 0x02, "Alt": 0x01, "Shift": 0x04}
_MOD_NAMES = {name.casefold(): name for name in _MODIFIERS} | {"control": "Ctrl"}
_KEY_CODES = {
    **{c: ord(c) for c in ascii_uppercase + digits},
    **{f"F{n}": 0x6F + n for n in range(1, 12)},
    **{f"NumPad{n}": 0x60 + n for n in range(10)},
}
_VK_NAMES = {code: key for key, code in _KEY_CODES.items()}
_NAMES = {key.casefold(): key for key in _KEY_CODES}
for _digit in digits:
    _NAMES[f"kp_{_digit}"] = _NAMES[f"小键盘{_digit}"] = f"NumPad{_digit}"


def canonical(text: str) -> str:
    """Normalize spelling and modifier order. Reject ambiguous or reserved keys."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请选择快捷键。")
    parts = [part.strip().casefold() for part in text.split("+")]
    modifiers: set[str] = set()
    for part in parts[:-1]:
        if part not in _MOD_NAMES:
            raise ValueError("修饰键只支持 Ctrl、Alt、Shift。")
        modifier = _MOD_NAMES[part]
        if modifier in modifiers:
            raise ValueError(f"修饰键 {modifier} 重复。")
        modifiers.add(modifier)
    primary = parts[-1].replace(" ", "")
    if primary == "f12":
        raise ValueError("F12 由 Windows 调试器保留，请换一个键。")
    key = _NAMES.get(primary)
    if key is None:
        raise ValueError("可用小键盘数字、F1 至 F11，或修饰键搭配字母、数字。")
    if len(key) == 1 and not modifiers:
        raise ValueError("普通字母和主键区数字需要搭配 Ctrl、Alt 或 Shift。")
    if (key == "F4" and "Alt" in modifiers) or (key.startswith("NumPad") and modifiers == {"Alt"}):
        raise ValueError("该组合用于 Windows 窗口操作或字符输入，请换一个快捷键。")
    return "+".join([m for m in _MODIFIERS if m in modifiers] + [key])


def validate(bindings: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(bindings, Mapping) or set(bindings) != set(DEFAULT_HOTKEYS):
        raise ValueError("快捷键配置应同时包含 toggle（开始/停止）和 calibrate（校准）。")
    result = {action: canonical(bindings[action]) for action in DEFAULT_HOTKEYS}
    if result["toggle"] == result["calibrate"]:
        raise ValueError("开始/停止与校准不能使用同一个快捷键。")
    return result


def display(text: str) -> str:
    return canonical(text).replace("NumPad", "小键盘 ")


def registration(text: str) -> tuple[int, int]:
    """Return (RegisterHotKey modifier mask, virtual key)."""
    *modifiers, key = canonical(text).split("+")
    return sum(_MODIFIERS[modifier] for modifier in modifiers), _KEY_CODES[key]


def _windows_logo_held(event) -> bool:
    # Tk's Windows backend has no reliable Win-key bit in event.state. Check
    # the current GUI thread's message-time key state for real Tk events.
    if sys.platform != "win32" or not hasattr(event, "widget"):
        return False
    get_state = ctypes.WinDLL("user32").GetKeyState
    get_state.argtypes = [ctypes.c_int]
    get_state.restype = ctypes.c_int16
    return any(get_state(vk) & 0x8000 for vk in (0x5B, 0x5C))


def from_event(event) -> str | None:
    """Decode a Windows Tk KeyPress. A modifier alone awaits the next key."""
    symbol = str(getattr(event, "keysym", ""))
    vk = int(getattr(event, "keycode", 0) or 0)
    if symbol in ("Win_L", "Win_R", "Super_L", "Super_R", "Meta_L", "Meta_R") or vk in (0x5B, 0x5C):
        raise ValueError("Windows 徽标键组合由系统保留，请换一个快捷键。")
    if symbol.startswith(("Shift_", "Control_", "Alt_")) or vk in (
        0x10,
        0x11,
        0x12,
        *range(0xA0, 0xA6),
    ):
        return None
    # Windows Tk sometimes reports a keypad digit as keysym '9', the same as
    # the number row. Its virtual key code reliably distinguishes the two.
    key = _VK_NAMES.get(vk, symbol)
    state = int(getattr(event, "state", 0) or 0)
    modifiers = []
    if state & 0x04:
        modifiers.append("Ctrl")
    # On Windows Tk Mod1 (0x08) is Num Lock, Mod2 (0x10) is Alt.
    if state & (0x10 | 0x20000):
        modifiers.append("Alt")
    if state & 0x01:
        modifiers.append("Shift")
    if state & (0x40 | 0x10000) or _windows_logo_held(event):
        raise ValueError("系统修饰键组合不能用于本助手。")
    return canonical("+".join([*modifiers, key]))
