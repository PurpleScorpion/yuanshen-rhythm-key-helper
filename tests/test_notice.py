import sys
from pathlib import Path

import pytest

from rhythm_helper import app, notice, notice_ui


def test_only_explicit_acceptance_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    responses = iter([False, True])
    monkeypatch.setattr(notice_ui, "show_notice", lambda *, required: required and next(responses))
    assert not notice.ensure_accepted(interactive=True)
    assert not notice._record_path().exists()
    assert notice.ensure_accepted(interactive=True)
    assert notice._record_path().read_bytes() == b"accepted\n"
    assert notice.ensure_accepted(interactive=True)
    assert notice.ensure_accepted(interactive=False)


def test_incomplete_record_is_not_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = notice._record_path()
    path.parent.mkdir()
    path.write_bytes(b"accept")
    assert not notice.ensure_accepted(interactive=False)


def test_cannot_start_if_acceptance_cannot_be_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(notice_ui, "show_notice", lambda *, required: True)

    def unwritable(source, target):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "replace", unwritable)
    with pytest.raises(RuntimeError, match="无法保存"):
        notice.ensure_accepted(interactive=True)
    assert list(notice._record_path().parent.iterdir()) == []


@pytest.mark.parametrize("args", [[], ["--dry-run"], ["--calibration-demo"]])
def test_decline_stops_before_loading_config_or_opening_any_mode(tmp_path, monkeypatch, args):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["helper", *args])
    monkeypatch.setattr(notice_ui, "show_notice", lambda *, required: False)
    monkeypatch.setattr(app, "load_config", lambda *a: pytest.fail("read config after decline"))
    monkeypatch.setattr(app, "practice_calibration", lambda *a: pytest.fail("opened tutorial"))
    assert app.main() == 0
    assert not notice._record_path().exists()


def test_unaccepted_inspect_is_noninteractive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["helper", "--inspect", "nonexistent.png"])
    monkeypatch.setattr(notice_ui, "show_notice", lambda **kw: pytest.fail("unexpected dialog"))
    assert app.main() == 1
    assert "我接受" in capsys.readouterr().err
