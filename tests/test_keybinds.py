from types import SimpleNamespace

import pytest

from rhythm_helper import keybinds


def test_canonical_order_and_number_pad_aliases():
    assert keybinds.canonical("shift + CONTROL + alt + k") == "Ctrl+Alt+Shift+K"
    assert keybinds.canonical("Ctrl+小键盘 3") == "Ctrl+NumPad3"
    assert keybinds.display("ctrl+KP_3") == "Ctrl+小键盘 3"
    assert keybinds.validate(keybinds.DEFAULT_HOTKEYS) == {"toggle": "NumPad9", "calibrate": "F6"}
    assert keybinds.registration("Ctrl+Alt+K") == (0x03, 0x4B)
    assert keybinds.registration("NumPad9") == (0, 0x69)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "A",
        "9",
        "Home",
        "Ctrl+Tab",
        "Ctrl++Q",
        "Ctrl",
        "Alt+F4",
        "F12",
        "Win+L",
        "Alt+NumPad7",
        "Ctrl+ctrl+A",
    ],
)
def test_disallowed_or_reserved_bindings(bad):
    with pytest.raises(ValueError):
        keybinds.canonical(bad)


@pytest.mark.parametrize(
    "bindings",
    [
        None,
        {"toggle": "F8"},
        {"toggle": "F8", "calibrate": "F6", "extra": "F7"},
        {"toggle": "Ctrl+Shift+P", "calibrate": "shift+ctrl+p"},
    ],
)
def test_requires_two_distinct_known_actions(bindings):
    with pytest.raises(ValueError):
        keybinds.validate(bindings)


def test_windows_tk_num_lock_is_not_alt_and_keypad_digit_is_not_number_row():
    assert keybinds.from_event(SimpleNamespace(keysym="9", keycode=0x69, state=0x08)) == "NumPad9"
    assert (
        keybinds.from_event(SimpleNamespace(keysym="KP_9", keycode=0, state=0x04)) == "Ctrl+NumPad9"
    )
    with pytest.raises(ValueError):
        keybinds.from_event(SimpleNamespace(keysym="9", keycode=0x39, state=0x08))
    with pytest.raises(ValueError):
        keybinds.from_event(SimpleNamespace(keysym="Prior", keycode=0x21, state=0))


@pytest.mark.parametrize("alt_state", [0x10, 0x20000])
def test_capture_modifiers_using_windows_tk_state_and_physical_key(alt_state):
    event = SimpleNamespace(keysym="??", keycode=0x4B, state=alt_state | 0x05 | 0x08)
    assert keybinds.from_event(event) == "Ctrl+Alt+Shift+K"


def test_modifier_only_waits_and_windows_shortcuts_are_rejected():
    assert keybinds.from_event(SimpleNamespace(keysym="Control_L", keycode=0x11, state=0)) is None
    with pytest.raises(ValueError):
        keybinds.from_event(SimpleNamespace(keysym="Win_L", keycode=0x5B, state=0))
    with pytest.raises(ValueError):
        keybinds.from_event(SimpleNamespace(keysym="F6", keycode=0x75, state=0x40))
