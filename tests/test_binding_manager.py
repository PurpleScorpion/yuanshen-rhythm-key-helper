import json

import pytest

from rhythm_helper.binding_manager import BindingManager
from rhythm_helper.keybinds import DEFAULT_HOTKEYS
from rhythm_helper.settings import load_config


class Registrar:
    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.closed = False
        self.blocked = None

    def poll(self):
        return []

    def rebind(self, bindings):
        if self.blocked in bindings.values():
            raise RuntimeError("occupied")
        self.bindings = dict(bindings)

    def close(self):
        self.closed = True


NEW_KEYS = {"toggle": "F8", "calibrate": "Ctrl+F7"}


def test_v7_config_migrates_on_successful_apply(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"input_lead_ms": 15}', encoding="utf-8")
    manager = BindingManager(load_config(path), path, Registrar)
    manager.start()
    assert manager.service.bindings == DEFAULT_HOTKEYS
    assert manager.apply(NEW_KEYS) == NEW_KEYS
    again = BindingManager(load_config(path), path, Registrar)
    again.start()
    assert again.service.bindings == NEW_KEYS
    assert again.settings["input_lead_ms"] == 15


def test_conflict_preserves_active_registration_and_saved_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkeys": DEFAULT_HOTKEYS}), encoding="utf-8")
    before = path.read_bytes()
    manager = BindingManager(load_config(path), path, Registrar)
    manager.start()
    manager.service.blocked = "F8"
    with pytest.raises(RuntimeError, match="occupied"):
        manager.apply(NEW_KEYS)
    assert manager.service.bindings == DEFAULT_HOTKEYS
    assert manager.bindings == DEFAULT_HOTKEYS
    assert path.read_bytes() == before


def test_write_failure_restores_registered_shortcuts(tmp_path):
    path = tmp_path / "unwritable" / "config.json"
    manager = BindingManager(load_config(path), path, Registrar)
    manager.start()
    with pytest.raises(RuntimeError, match="未保存"):
        manager.apply(NEW_KEYS)
    assert manager.service.bindings == DEFAULT_HOTKEYS
    assert manager.bindings == DEFAULT_HOTKEYS
    assert not path.exists()


def test_can_recover_from_conflict_at_startup(tmp_path):
    def register(bindings):
        if bindings == DEFAULT_HOTKEYS:
            raise RuntimeError("occupied")
        return Registrar(bindings)

    path = tmp_path / "config.json"
    manager = BindingManager(load_config(path), path, register)
    with pytest.raises(RuntimeError):
        manager.start()
    assert manager.service is None
    manager.apply(NEW_KEYS)
    assert load_config(path)["hotkeys"] == NEW_KEYS
    assert manager.service.bindings == NEW_KEYS
