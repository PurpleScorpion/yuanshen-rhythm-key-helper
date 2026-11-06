"""Remember explicit acceptance for the current Windows account."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def _record_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "yuanshen-rhythm-key-helper" / "notice-accepted"


def ensure_accepted(*, interactive: bool) -> bool:
    record = _record_path()
    try:
        if record.read_bytes() == b"accepted\n":
            return True
    except FileNotFoundError:
        pass
    except OSError as error:
        raise RuntimeError(f"无法读取使用声明记录：{record}\n{error}") from error

    if not interactive:
        return False
    from .notice_ui import show_notice

    if not show_notice(required=True):
        return False

    temp = None
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=record.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(b"accepted\n")
        temp.replace(record)
    except OSError as error:
        raise RuntimeError(
            f"无法保存使用声明记录，请检查此目录的写入权限：{record.parent}\n{error}"
        ) from error
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return True
