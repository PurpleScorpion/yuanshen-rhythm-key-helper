"""Small Win32 adapter. Importing this module never sends keyboard input."""

from __future__ import annotations

import ctypes
import ntpath
import os
from dataclasses import dataclass
from typing import Any

# Use fixed-width integers: Win32 LONG/DWORD stay 32-bit on 64-bit Windows.
_WORD = ctypes.c_uint16
_DWORD = ctypes.c_uint32
_LONG = ctypes.c_int32
_ULONG_PTR = ctypes.c_size_t
_HWND = ctypes.c_void_p
_ENUMWINDOWSPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_int, _HWND, ctypes.c_ssize_t
)


class _POINT(ctypes.Structure):
    _fields_ = [("x", _LONG), ("y", _LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", _LONG), ("top", _LONG), ("right", _LONG), ("bottom", _LONG)]


class _TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", _DWORD)]


class WindowUnavailableError(ValueError):
    """A valid window temporarily has no capturable client area."""


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", _LONG),
        ("dy", _LONG),
        ("mouseData", _DWORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", _WORD),
        ("wScan", _WORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", _DWORD), ("wParamL", _WORD), ("wParamH", _WORD)]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT is essential even though only keyboard events are sent:
    # it determines the ABI size of INPUT (40 bytes on x64, 28 on x86).
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", _DWORD), ("data", _INPUTUNION)]


_user32: Any = None
_kernel32: Any = None
_advapi32: Any = None


def _api() -> Any:
    global _user32
    if os.name != "nt":
        raise RuntimeError("屏幕坐标与按键控制仅支持 Windows。")
    if _user32 is None:
        api = ctypes.WinDLL("user32", use_last_error=True)
        declarations = {
            "GetForegroundWindow": ([], _HWND),
            "GetWindowTextLengthW": ([_HWND], ctypes.c_int),
            "GetWindowTextW": ([_HWND, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_int16),
            "GetKeyState": ([ctypes.c_int], ctypes.c_int16),
            "GetCursorPos": ([ctypes.POINTER(_POINT)], ctypes.c_int),
            "IsWindow": ([_HWND], ctypes.c_int),
            "IsWindowVisible": ([_HWND], ctypes.c_int),
            "IsIconic": ([_HWND], ctypes.c_int),
            "EnumWindows": ([_ENUMWINDOWSPROC, ctypes.c_ssize_t], ctypes.c_int),
            "GetWindowThreadProcessId": ([_HWND, ctypes.POINTER(_DWORD)], _DWORD),
            "GetClassNameW": ([_HWND, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
            "ShowWindow": ([_HWND, ctypes.c_int], ctypes.c_int),
            "SetForegroundWindow": ([_HWND], ctypes.c_int),
            "GetClientRect": ([_HWND, ctypes.POINTER(_RECT)], ctypes.c_int),
            "ClientToScreen": ([_HWND, ctypes.POINTER(_POINT)], ctypes.c_int),
            "SendInput": ([_DWORD, ctypes.POINTER(_INPUT), ctypes.c_int], _DWORD),
            "SetProcessDPIAware": ([], ctypes.c_int),
        }
        for name, (argtypes, restype) in declarations.items():
            function = getattr(api, name)
            function.argtypes = argtypes
            function.restype = restype
        if hasattr(api, "SetProcessDpiAwarenessContext"):
            api.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            api.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        _user32 = api
    return _user32


def _kernel_api() -> Any:
    global _kernel32
    if os.name != "nt":
        raise RuntimeError("游戏窗口查找仅支持 Windows。")
    if _kernel32 is None:
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [_DWORD, ctypes.c_int, _DWORD]
        api.OpenProcess.restype = ctypes.c_void_p
        api.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            _DWORD,
            ctypes.c_wchar_p,
            ctypes.POINTER(_DWORD),
        ]
        api.QueryFullProcessImageNameW.restype = ctypes.c_int
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        api.CloseHandle.restype = ctypes.c_int
        api.GetCurrentProcess.argtypes = []
        api.GetCurrentProcess.restype = ctypes.c_void_p
        _kernel32 = api
    return _kernel32


def _security_api() -> Any:
    global _advapi32
    if os.name != "nt":
        raise RuntimeError("进程权限查询仅支持 Windows。")
    if _advapi32 is None:
        api = ctypes.WinDLL("advapi32", use_last_error=True)
        api.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            _DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        api.OpenProcessToken.restype = ctypes.c_int
        api.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            _DWORD,
            ctypes.POINTER(_DWORD),
        ]
        api.GetTokenInformation.restype = ctypes.c_int
        _advapi32 = api
    return _advapi32


def _last_error(operation: str) -> OSError:
    code = ctypes.get_last_error()
    if code:
        return ctypes.WinError(code)
    return OSError(f"{operation} 失败，Windows 未返回错误码。")


def enable_dpi_awareness() -> None:
    """Call before creating any GUI or screen-capture object."""
    api = _api()
    if hasattr(api, "SetProcessDpiAwarenessContext"):
        # PER_MONITOR_AWARE_V2, then V1 for older Windows 10 releases.
        for context in (-4, -3):
            ctypes.set_last_error(0)
            if api.SetProcessDpiAwarenessContext(ctypes.c_void_p(context)):
                return
            error = ctypes.get_last_error()
            if error == 5:  # Already set by a manifest or an earlier call.
                return
            if error != 87:  # ERROR_INVALID_PARAMETER: try older mode.
                raise _last_error("SetProcessDpiAwarenessContext")
    ctypes.set_last_error(0)
    if not api.SetProcessDPIAware():
        raise _last_error("SetProcessDPIAware")


def foreground_window() -> int:
    """Return the foreground HWND, or zero during a focus transition."""
    return int(_api().GetForegroundWindow() or 0)


def _token_elevation(process_handle: int) -> bool:
    """Query a process token with TOKEN_QUERY only; never adjust privileges."""
    security, kernel = _security_api(), _kernel_api()
    token = ctypes.c_void_p()
    ctypes.set_last_error(0)
    if not security.OpenProcessToken(process_handle, 0x0008, ctypes.byref(token)):
        raise _last_error("OpenProcessToken")
    try:
        elevation = _TOKEN_ELEVATION()
        returned = _DWORD()
        ctypes.set_last_error(0)
        if not security.GetTokenInformation(
            token.value,
            20,  # TokenElevation
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            raise _last_error("GetTokenInformation(TokenElevation)")
        if returned.value != ctypes.sizeof(elevation):
            raise OSError("TokenElevation 返回了无法识别的长度。")
        return bool(elevation.TokenIsElevated)
    finally:
        kernel.CloseHandle(token.value)


def is_elevated() -> bool:
    """Return the current process's elevation; query failures raise OSError."""
    # GetCurrentProcess returns a pseudo-handle which must not be closed.
    return _token_elevation(_kernel_api().GetCurrentProcess())


def window_elevation(hwnd: int) -> bool | None:
    """Read a target's elevation, or None when the target cannot be queried.

    Access denied, an exited process and a disappearing HWND are unknown; none
    of them is evidence that the game is running without elevation.
    """
    api = _api()
    if not hwnd or not api.IsWindow(hwnd):
        return None
    pid = _DWORD()
    if not api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        return None
    kernel = _kernel_api()
    process = kernel.OpenProcess(0x1000, False, pid.value)
    if not process:
        return None
    try:
        try:
            return _token_elevation(process)
        except OSError:
            return None
    finally:
        kernel.CloseHandle(process)


def _require_window(hwnd: int) -> Any:
    api = _api()
    if not hwnd or not api.IsWindow(hwnd):
        raise ValueError("目标窗口已经关闭或窗口句柄无效。")
    return api


def window_title(hwnd: int) -> str:
    api = _require_window(hwnd)
    size = max(1, api.GetWindowTextLengthW(hwnd) + 1)
    buffer = ctypes.create_unicode_buffer(size)
    ctypes.set_last_error(0)
    length = api.GetWindowTextW(hwnd, buffer, size)
    if length == 0 and ctypes.get_last_error():
        raise _last_error("GetWindowTextW")
    return buffer.value


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    # Empty only for the conservative Unity class/title permission fallback.
    process_name: str


def _process_name(pid: int) -> tuple[str | None, bool]:
    """Read the exe basename with limited query rights, never process memory.

    The second item is true only for a permission failure, not a closed process
    or an arbitrary query error. Every successfully opened handle is closed.
    """
    api = _kernel_api()
    ctypes.set_last_error(0)
    handle = api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None, ctypes.get_last_error() in (5, 1314)
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = _DWORD(len(buffer))
        ctypes.set_last_error(0)
        if not api.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None, ctypes.get_last_error() in (5, 1314)
        return ntpath.basename(buffer.value), False
    finally:
        api.CloseHandle(handle)


def find_game_windows() -> list[GameWindow]:
    """Find visible Genshin windows, including minimized windows.

    Titles containing the game's name do not identify a game. A readable exe
    must match the whitelist exactly; only an access-denied process query may
    fall back to the exact Unity window class and title together.
    """
    api = _api()
    handles: list[int] = []

    @_ENUMWINDOWSPROC
    def collect(hwnd: int, _lparam: int) -> int:
        handles.append(int(hwnd))
        return 1

    ctypes.set_last_error(0)
    if not api.EnumWindows(collect, 0):
        raise _last_error("EnumWindows")
    candidates: list[GameWindow] = []
    own_pid = os.getpid()
    for hwnd in handles:
        if not api.IsWindowVisible(hwnd):
            continue
        pid = _DWORD()
        if not api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            continue
        if not pid.value or pid.value == own_pid:
            continue
        process_name, permission_denied = _process_name(pid.value)
        if process_name is not None and process_name.casefold() not in {
            "yuanshen.exe",
            "genshinimpact.exe",
        }:
            continue
        if process_name is None and not permission_denied:
            continue
        # A window may disappear between enumeration and its metadata query.
        try:
            title = window_title(hwnd)
        except (OSError, ValueError):
            continue
        if process_name is None:
            class_name = ctypes.create_unicode_buffer(256)
            if not api.GetClassNameW(hwnd, class_name, len(class_name)):
                continue
            if class_name.value != "UnityWndClass" or title not in ("原神", "Genshin Impact"):
                continue
        candidates.append(GameWindow(hwnd, title, process_name or ""))
    return candidates


def activate_window(hwnd: int) -> bool:
    """Restore and request focus once; Windows can deny foreground activation."""
    api = _api()
    if not hwnd or not api.IsWindow(hwnd):
        return False
    if api.IsIconic(hwnd):
        api.ShowWindow(hwnd, 9)  # SW_RESTORE
    api.SetForegroundWindow(hwnd)
    return int(api.GetForegroundWindow() or 0) == hwnd


def is_numlock_on() -> bool:
    return bool(_api().GetKeyState(0x90) & 1)  # VK_NUMLOCK toggle bit


def key_is_down(vk: int) -> bool:
    if not 1 <= vk <= 254:
        raise ValueError("虚拟键码必须在 1 到 254 之间。")
    # The low bit is shared with other processes; only the high bit is reliable.
    return bool(_api().GetAsyncKeyState(vk) & 0x8000)


def cursor_position() -> tuple[int, int]:
    api = _api()
    point = _POINT()
    ctypes.set_last_error(0)
    if not api.GetCursorPos(ctypes.byref(point)):
        raise _last_error("GetCursorPos")
    return point.x, point.y


def foreground_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return the client area as physical screen (left, top, width, height)."""
    api = _require_window(hwnd)
    if api.IsIconic(hwnd):
        raise WindowUnavailableError("目标窗口已最小化，请先恢复游戏窗口。")
    rect, point = _RECT(), _POINT()
    ctypes.set_last_error(0)
    if not api.GetClientRect(hwnd, ctypes.byref(rect)):
        error = _last_error("GetClientRect")
        _require_window(hwnd)
        if api.IsIconic(hwnd):
            raise WindowUnavailableError("目标窗口正在最小化，请等待游戏恢复。")
        raise error
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise WindowUnavailableError("目标窗口没有可用的画面区域。")
    ctypes.set_last_error(0)
    if not api.ClientToScreen(hwnd, ctypes.byref(point)):
        error = _last_error("ClientToScreen")
        _require_window(hwnd)
        if api.IsIconic(hwnd):
            raise WindowUnavailableError("目标窗口正在最小化，请等待游戏恢复。")
        raise error
    if api.IsIconic(hwnd):
        raise WindowUnavailableError("目标窗口正在最小化，请等待游戏恢复。")
    return point.x + rect.left, point.y + rect.top, width, height


class KeyboardOutput:
    """Own each successful key-down until its matching key-up succeeds.

    Calls are synchronous and intended for the main runtime thread. Distinct
    keys can stay down together; repeated press/release calls are idempotent.
    """

    SCAN_CODES = {"a": 0x1E, "s": 0x1F, "d": 0x20, "j": 0x24, "k": 0x25, "l": 0x26}

    def __init__(self) -> None:
        self._api = _api()
        self._held: set[str] = set()

    @property
    def held_keys(self) -> frozenset[str]:
        return frozenset(self._held)

    @classmethod
    def _key(cls, key: str) -> str:
        normalized = key.lower()
        if normalized not in cls.SCAN_CODES:
            raise ValueError(f"不支持的轨道按键：{key!r}；仅支持 A/S/D/J/K/L。")
        return normalized

    def _send(self, key: str, *, released: bool) -> None:
        event = _INPUT()
        event.type = 1  # INPUT_KEYBOARD
        event.ki = _KEYBDINPUT(0, self.SCAN_CODES[key], 0x0008 | (0x0002 if released else 0), 0, 0)
        ctypes.set_last_error(0)
        sent = self._api.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))
        if sent != 1:
            error = _last_error("SendInput")
            if not ctypes.get_last_error():
                error = OSError(
                    "SendInput 未发送按键。请确认游戏和脚本权限级别一致；"
                    "该接口无法绕过游戏对模拟输入的限制。"
                )
            raise error

    def press(self, key: str) -> None:
        key = self._key(key)
        if key not in self._held:
            self._send(key, released=False)
            self._held.add(key)

    def release(self, key: str) -> None:
        key = self._key(key)
        if key in self._held:
            self._send(key, released=True)
            # Keep ownership when SendInput raises, so cleanup can retry.
            self._held.remove(key)

    def release_all(self) -> None:
        """Try every owned key, retaining failed releases for a later retry."""
        failures: list[OSError] = []
        for key in sorted(self._held):
            try:
                self.release(key)
            except OSError as error:
                failures.append(error)
        if failures:
            raise OSError(
                "部分按键未能松开，待重试：" + ", ".join(sorted(self._held))
            ) from failures[0]
