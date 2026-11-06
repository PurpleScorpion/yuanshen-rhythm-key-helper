"""Small non-activating Win32 status overlay; no keyboard input is generated.

Create, update, pump and close the display from the same main thread. Call
``pump`` each loop iteration so repaint messages can be handled without a
second GUI event loop. Creating the object leaves its window hidden until the
first ``update``. The optional ``beep`` function is independent of the window.
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Any

from . import PRODUCT_NAME

_DWORD = ctypes.c_uint32
_LONG = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_LPARAM = ctypes.c_ssize_t
_WPARAM = ctypes.c_size_t
_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_WNDPROC = _CALLBACK(_LPARAM, _HANDLE, _DWORD, _WPARAM, _LPARAM)


class _POINT(ctypes.Structure):
    _fields_ = [("x", _LONG), ("y", _LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", _LONG), ("top", _LONG), ("right", _LONG), ("bottom", _LONG)]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", _DWORD),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", _HANDLE),
        ("hIcon", _HANDLE),
        ("hCursor", _HANDLE),
        ("hbrBackground", _HANDLE),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", _HANDLE),
        ("fErase", _LONG),
        ("rcPaint", _RECT),
        ("fRestore", _LONG),
        ("fIncUpdate", _LONG),
        ("rgbReserved", ctypes.c_ubyte * 32),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", _HANDLE),
        ("message", _DWORD),
        ("wParam", _WPARAM),
        ("lParam", _LPARAM),
        ("time", _DWORD),
        ("pt", _POINT),
        ("lPrivate", _DWORD),
    ]


_STATES = {
    "idle": ("已停止", (167, 176, 190)),
    "waiting": ("等待原神", (255, 190, 86)),
    "running": ("运行中", (104, 232, 154)),
    "paused": ("已停止", (167, 176, 190)),
    "error": ("错误", (255, 116, 116)),
}


def _rgb(red: int, green: int, blue: int) -> int:
    return red | green << 8 | blue << 16


def _declare(api: Any, declarations: dict[str, tuple[list, Any]]) -> None:
    for name, (arguments, result) in declarations.items():
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result


def beep(state: str) -> None:
    """Queue a system sound; disabled/missing system audio is harmless."""
    if os.name != "nt":
        return
    try:
        import winsound

        sounds = {
            "running": winsound.MB_ICONASTERISK,
            "waiting": winsound.MB_ICONEXCLAMATION,
            "error": winsound.MB_ICONHAND,
        }
        # MessageBeep queues the sound asynchronously, unlike Beep(duration).
        winsound.MessageBeep(sounds.get(state, winsound.MB_OK))
    except (ImportError, RuntimeError, OSError):
        pass


class StatusDisplay:
    """Click-through, topmost status display that never takes foreground focus."""

    WIDTH = 480
    HEIGHT = 76
    # WS_EX_NOACTIVATE | TOOLWINDOW | TOPMOST | TRANSPARENT | LAYERED.
    EX_STYLE = 0x08000000 | 0x00000080 | 0x00000008 | 0x00000020 | 0x00080000

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("状态悬浮条仅支持 Windows。")
        self._thread_id = threading.get_ident()
        self._hwnd = 0
        self._atom = 0
        self._fonts: list[int] = []
        self._closed = False
        self._callback_error: Exception | None = None
        self._state = "idle"
        self.toggle_label = ""
        self._detail = "等待启动。"
        self._placement: tuple[int, int, int, int] | None = None
        self._class_name = f"RhythmHelperStatus_{os.getpid()}_{id(self):x}"
        try:
            self._load_api()
            self._instance = self._kernel.GetModuleHandleW(None)
            if not self._instance:
                raise ctypes.WinError(ctypes.get_last_error())
            self._procedure = _WNDPROC(self._window_proc)
            window_class = _WNDCLASS()
            window_class.lpfnWndProc = self._procedure
            window_class.hInstance = self._instance
            window_class.lpszClassName = self._class_name
            self._atom = self._user.RegisterClassW(ctypes.byref(window_class))
            if not self._atom:
                raise ctypes.WinError(ctypes.get_last_error())
            for height, weight in ((19, 600), (15, 400)):
                font = self._gdi.CreateFontW(
                    -height, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI"
                )
                if not font:
                    raise RuntimeError("无法创建状态条字体。")
                self._fonts.append(font)
            self._hwnd = self._user.CreateWindowExW(
                self.EX_STYLE,
                self._class_name,
                f"{PRODUCT_NAME} · 状态",
                0x80000000,  # WS_POPUP, initially hidden.
                20,
                110,
                self.WIDTH,
                self.HEIGHT,
                None,
                None,
                self._instance,
                None,
            )
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self._user.SetLayeredWindowAttributes(self._hwnd, 0, 244, 2):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception as error:
            self.close()
            raise RuntimeError(f"无法创建状态悬浮条：{error}") from error

    def _load_api(self) -> None:
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        integer, string = ctypes.c_int, ctypes.c_wchar_p
        _declare(
            self._user,
            {
                "RegisterClassW": ([ctypes.POINTER(_WNDCLASS)], ctypes.c_uint16),
                "UnregisterClassW": ([string, _HANDLE], integer),
                "CreateWindowExW": (
                    [_DWORD, string, string, _DWORD] + [integer] * 4 + [_HANDLE] * 4,
                    _HANDLE,
                ),
                "DefWindowProcW": ([_HANDLE, _DWORD, _WPARAM, _LPARAM], _LPARAM),
                "SetLayeredWindowAttributes": (
                    [_HANDLE, _DWORD, ctypes.c_ubyte, _DWORD],
                    integer,
                ),
                "SetWindowPos": ([_HANDLE, _HANDLE] + [integer] * 4 + [_DWORD], integer),
                "InvalidateRect": ([_HANDLE, ctypes.POINTER(_RECT), integer], integer),
                "DestroyWindow": ([_HANDLE], integer),
                "BeginPaint": ([_HANDLE, ctypes.POINTER(_PAINTSTRUCT)], _HANDLE),
                "EndPaint": ([_HANDLE, ctypes.POINTER(_PAINTSTRUCT)], integer),
                "GetClientRect": ([_HANDLE, ctypes.POINTER(_RECT)], integer),
                "FillRect": ([_HANDLE, ctypes.POINTER(_RECT), _HANDLE], integer),
                "DrawTextW": ([_HANDLE, string, integer, ctypes.POINTER(_RECT), _DWORD], integer),
                "PeekMessageW": (
                    [ctypes.POINTER(_MSG), _HANDLE, _DWORD, _DWORD, _DWORD],
                    integer,
                ),
                "TranslateMessage": ([ctypes.POINTER(_MSG)], integer),
                "DispatchMessageW": ([ctypes.POINTER(_MSG)], _LPARAM),
                "SystemParametersInfoW": ([_DWORD, _DWORD, _HANDLE, _DWORD], integer),
            },
        )
        _declare(
            self._gdi,
            {
                "CreateSolidBrush": ([_DWORD], _HANDLE),
                "DeleteObject": ([_HANDLE], integer),
                "SelectObject": ([_HANDLE, _HANDLE], _HANDLE),
                "SetTextColor": ([_HANDLE, _DWORD], _DWORD),
                "SetBkMode": ([_HANDLE, integer], integer),
                "CreateFontW": ([integer] * 5 + [_DWORD] * 8 + [string], _HANDLE),
            },
        )
        _declare(self._kernel, {"GetModuleHandleW": ([string], _HANDLE)})

    def _require_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("状态条必须由创建它的线程更新和关闭。")

    def update(
        self,
        state: str,
        detail: str = "",
        rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._require_thread()
        if self._closed or not self._hwnd:
            raise RuntimeError("状态悬浮条已关闭。")
        if state not in _STATES:
            raise ValueError(f"未知状态：{state}")
        if rect is None:
            desktop = _RECT()
            if self._user.SystemParametersInfoW(0x0030, 0, ctypes.byref(desktop), 0):
                rect = (
                    desktop.left,
                    desktop.top,
                    desktop.right - desktop.left,
                    desktop.bottom - desktop.top,
                )
            else:
                rect = (0, 0, 1920, 1080)
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            raise ValueError("状态条定位区域必须具有正的宽高。")
        placement = (
            int(left + 20),
            int(top + min(110, max(8, height - self.HEIGHT - 8))),
            min(self.WIDTH, max(240, int(width - 40))),
            self.HEIGHT,
        )
        detail = detail.strip() or f"{self.toggle_label} 启停"
        changed = state != self._state or detail != self._detail
        self._state, self._detail = state, detail
        if placement != self._placement:
            # NOACTIVATE | SHOWWINDOW | NOOWNERZORDER. In particular, avoid
            # ShowWindow's first-call STARTUPINFO behaviour and all focus APIs.
            if not self._user.SetWindowPos(self._hwnd, _HANDLE(-1), *placement, 0x0250):
                raise RuntimeError("无法显示或定位状态悬浮条。")
            self._placement = placement
            changed = True
        if changed and not self._user.InvalidateRect(self._hwnd, None, 0):
            raise RuntimeError("无法刷新状态悬浮条。")

    def pump(self) -> None:
        self._require_thread()
        if self._closed:
            return
        if not self._hwnd:
            raise RuntimeError("状态悬浮条已被关闭。")
        message = _MSG()
        # Filter to our own HWND: do not consume another UI's messages or quit.
        for _ in range(32):
            if not self._user.PeekMessageW(ctypes.byref(message), self._hwnd, 0, 0, 1):
                break
            self._user.TranslateMessage(ctypes.byref(message))
            self._user.DispatchMessageW(ctypes.byref(message))
        if self._callback_error is not None:
            raise RuntimeError(f"状态条绘制失败：{self._callback_error}") from self._callback_error

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        try:
            if message == 0x000F:  # WM_PAINT
                self._paint(hwnd)
                return 0
            if message == 0x0014:  # WM_ERASEBKGND; paint fills the full area.
                return 1
            if message == 0x0021:  # WM_MOUSEACTIVATE
                return 3  # MA_NOACTIVATE
            if message == 0x0084:  # WM_NCHITTEST
                return -1  # HTTRANSPARENT; layered transparent style also passes clicks.
            if message == 0x0082:  # WM_NCDESTROY
                self._hwnd = 0
        except Exception as error:
            # Exceptions must not escape a ctypes callback into native code.
            self._callback_error = error
        return self._user.DefWindowProcW(hwnd, message, wparam, lparam)

    def _fill(self, hdc: int, rect: _RECT, color: tuple[int, int, int]) -> None:
        brush = self._gdi.CreateSolidBrush(_rgb(*color))
        if not brush:
            raise RuntimeError("无法创建状态条画刷。")
        try:
            if not self._user.FillRect(hdc, ctypes.byref(rect), brush):
                raise RuntimeError("无法绘制状态条背景。")
        finally:
            self._gdi.DeleteObject(brush)

    def _paint(self, hwnd: int) -> None:
        paint = _PAINTSTRUCT()
        hdc = self._user.BeginPaint(hwnd, ctypes.byref(paint))
        if not hdc:
            raise RuntimeError("无法取得状态条绘图区域。")
        try:
            rect = _RECT()
            if not self._user.GetClientRect(hwnd, ctypes.byref(rect)):
                raise RuntimeError("无法取得状态条大小。")
            label, accent = _STATES[self._state]
            self._fill(hdc, rect, (20, 26, 37))
            self._fill(hdc, _RECT(0, 0, 5, rect.bottom), accent)
            self._gdi.SetBkMode(hdc, 1)  # TRANSPARENT text background.
            lines = (
                (f"{PRODUCT_NAME} | {label}  ·  {self.toggle_label} 启停", 6, 34, accent),
                (self._detail, 39, 66, (214, 221, 231)),
            )
            for font, (text, top, bottom, color) in zip(self._fonts, lines, strict=True):
                old_font = self._gdi.SelectObject(hdc, font)
                try:
                    self._gdi.SetTextColor(hdc, _rgb(*color))
                    text_rect = _RECT(17, top, rect.right - 12, bottom)
                    # SINGLELINE | VCENTER | NOPREFIX | END_ELLIPSIS.
                    self._user.DrawTextW(hdc, text, -1, ctypes.byref(text_rect), 0x8824)
                finally:
                    if old_font:
                        self._gdi.SelectObject(hdc, old_font)
        finally:
            self._user.EndPaint(hwnd, ctypes.byref(paint))

    def close(self) -> None:
        self._require_thread()
        if self._closed:
            return
        if self._hwnd:
            if not self._user.DestroyWindow(self._hwnd):
                raise RuntimeError("无法关闭状态悬浮条。")
            self._hwnd = 0
        for font in self._fonts:
            self._gdi.DeleteObject(font)
        self._fonts.clear()
        if self._atom:
            self._user.UnregisterClassW(self._class_name, self._instance)
            self._atom = 0
        self._closed = True
