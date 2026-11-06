"""Register global hotkeys on a dedicated Win32 message thread.

The UI thread may run OpenCV/Tk calibration loops without consuming this
thread's WM_HOTKEY messages. No keyboard hook, driver, or input injection is
used here. The caller should poll regularly and close in a finally block.
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from .keybinds import DEFAULT_HOTKEYS, registration, validate

_DWORD = ctypes.c_uint32
_HWND = ctypes.c_void_p
_WM_QUIT = 0x0012
_WM_HOTKEY = 0x0312
_WM_REBIND = 0x8001  # Private thread message (WM_APP+1).
_MOD_NOREPEAT = 0x4000
_STARTUP_TIMEOUT = 3.0
_SHUTDOWN_TIMEOUT = 2.0
_REBIND_TIMEOUT = 2.0


class _RegistrationConflict(RuntimeError):
    """A candidate shortcut could not be registered. Original keys still work."""


@dataclass
class _Rebind:
    bindings: dict[str, str]
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", _HWND),
        ("message", _DWORD),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", _DWORD),
        ("pt", _POINT),
        ("lPrivate", _DWORD),
    ]


def _load_api() -> tuple[Any, Any]:
    if os.name != "nt":
        raise RuntimeError("全局热键仅支持 Windows。")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "RegisterHotKey": ([_HWND, ctypes.c_int, _DWORD, _DWORD], ctypes.c_int),
        "UnregisterHotKey": ([_HWND, ctypes.c_int], ctypes.c_int),
        "PeekMessageW": (
            [ctypes.POINTER(_MSG), _HWND, _DWORD, _DWORD, _DWORD],
            ctypes.c_int,
        ),
        "GetMessageW": ([ctypes.POINTER(_MSG), _HWND, _DWORD, _DWORD], ctypes.c_int),
        "PostThreadMessageW": (
            [_DWORD, _DWORD, ctypes.c_size_t, ctypes.c_ssize_t],
            ctypes.c_int,
        ),
    }
    for name, (argtypes, restype) in declarations.items():
        function = getattr(user32, name)
        function.argtypes = argtypes
        function.restype = restype
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = _DWORD
    return user32, kernel32


def _api_error(operation: str) -> RuntimeError:
    return RuntimeError(f"{operation} 失败（Windows 错误码 {ctypes.get_last_error()}）。")


class GlobalHotkeys:
    """Own and change registrations on one Win32 thread with a message queue."""

    def __init__(self, bindings=None) -> None:
        self._bindings = validate(DEFAULT_HOTKEYS if bindings is None else bindings)
        self._pending: _Rebind | None = None
        self._user32, self._kernel32 = _load_api()
        self._events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._finished = threading.Event()
        self._failure: BaseException | None = None
        self._cleanup_failure: BaseException | None = None
        self._thread_id: int | None = None
        self._closed = False
        self._close_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="rhythm-global-hotkeys", daemon=True)
        try:
            self._thread.start()
        except RuntimeError as error:
            self._closed = True
            self._stopping.set()
            raise RuntimeError("无法启动全局热键线程，请关闭旧版程序后重试。") from error
        try:
            ready = self._ready.wait(_STARTUP_TIMEOUT)
        except BaseException:
            self.close()
            raise
        if not ready:
            try:
                self.close()
            except RuntimeError as cleanup_error:
                raise RuntimeError(
                    "全局热键线程启动超时，已请求停止；请完全退出程序后重试。"
                ) from cleanup_error
            raise RuntimeError("全局热键线程启动超时，已清理注册，请重新启动程序。")
        if self._failure is not None:
            failure = self._failure
            self.close()
            raise RuntimeError(str(failure)) from failure

    def _record_failure(self, error: BaseException) -> None:
        if self._failure is None:
            self._failure = error

    def _unregister(self, key: str, registered: dict[str, int]) -> None:
        identifier = registered[key]
        ctypes.set_last_error(0)
        if not self._user32.UnregisterHotKey(None, identifier):
            raise _api_error(f"UnregisterHotKey({identifier})")
        del registered[key]

    def _apply(self, bindings: dict[str, str], registered: dict[str, int]) -> dict[int, str]:
        # Keep all old physical combinations registered while staging new ones.
        # A swap therefore changes only our action map, without a reservation gap.
        staged = []
        try:
            for key in bindings.values():
                if self._stopping.is_set():
                    return {}
                if key in registered:
                    continue
                identifier = next(
                    i for i in range(1, len(registered) + 2) if i not in registered.values()
                )
                modifiers, vk = registration(key)
                ctypes.set_last_error(0)
                if not self._user32.RegisterHotKey(None, identifier, modifiers | _MOD_NOREPEAT, vk):
                    raise _RegistrationConflict(
                        f"{key} 全局热键注册失败（Windows 错误码 {ctypes.get_last_error()}）。"
                        "热键可能已被占用，请关闭旧版程序或换一个键。"
                    )
                registered[key] = identifier
                staged.append(key)
        except _RegistrationConflict:
            for key in reversed(staged):
                self._unregister(key, registered)
            raise
        # If any native unregister fails, the worker exits and cleans every
        # remaining known registration rather than continuing with a partial set.
        for key in tuple(registered):
            if key not in bindings.values():
                self._unregister(key, registered)
        return {registered[key]: action for action, key in bindings.items()}

    def _discard_old_commands(self) -> None:
        message = _MSG()
        while self._user32.PeekMessageW(ctypes.byref(message), None, _WM_HOTKEY, _WM_HOTKEY, 1):
            if message.message == _WM_QUIT:
                raise RuntimeError("全局热键消息线程已退出。")
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def _stop_failed_change(self, error: BaseException) -> None:
        self._record_failure(error)
        self._stopping.set()
        self._user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)

    def rebind(self, bindings) -> None:
        """Try both new shortcuts together. A registration conflict retains both old keys."""
        candidate = validate(bindings)
        with self._close_lock:
            if self._failure is not None:
                raise RuntimeError(f"全局热键不可用：{self._failure}") from self._failure
            if self._closed or self._stopping.is_set():
                raise RuntimeError("全局热键服务已关闭。")
            if candidate == self._bindings:
                return
            change = _Rebind(candidate)
            self._pending = change
            try:
                ctypes.set_last_error(0)
                if not self._user32.PostThreadMessageW(self._thread_id, _WM_REBIND, 0, 0):
                    raise _api_error("通知热键线程更新绑定")
                try:
                    completed = change.done.wait(_REBIND_TIMEOUT)
                except BaseException as error:
                    self._stop_failed_change(error)
                    raise
                if not completed:
                    # Once the caller can no longer know which registrations
                    # succeeded, suppress further actions and request teardown.
                    error = RuntimeError("更新快捷键超时；已请求停止热键服务。")
                    self._stop_failed_change(error)
                    raise error
                if change.error is not None:
                    raise RuntimeError(str(change.error)) from change.error
            finally:
                self._pending = None

    def _run(self) -> None:
        registered: dict[str, int] = {}
        try:
            message = _MSG()
            # Force creation of this thread's queue before publishing its ID.
            self._user32.PeekMessageW(ctypes.byref(message), None, 0x0400, 0x0400, 0)
            self._thread_id = int(self._kernel32.GetCurrentThreadId())
            if not self._thread_id:
                raise RuntimeError("无法取得全局热键线程编号。")
            actions = self._apply(self._bindings, registered)
            if self._stopping.is_set():
                return
            self._ready.set()
            while not self._stopping.is_set():
                ctypes.set_last_error(0)
                result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise _api_error("GetMessageW")
                if result == 0:
                    if not self._stopping.is_set():
                        raise RuntimeError("全局热键消息线程意外退出，请重新启动程序。")
                    break
                if message.message == _WM_HOTKEY and message.wParam in actions:
                    self._events.put(actions[message.wParam])
                elif message.message == _WM_REBIND:
                    change = self._pending
                    if change is None:
                        continue
                    try:
                        actions = self._apply(change.bindings, registered)
                        self._discard_old_commands()
                        self._bindings = change.bindings
                    except _RegistrationConflict as error:
                        change.error = error
                    except BaseException as error:
                        failure = RuntimeError(f"换键失败，已停止全局热键服务：{error}")
                        change.error = failure
                        self._record_failure(failure)
                        raise failure from error
                    finally:
                        change.done.set()
        except BaseException as error:
            # Surface thread failures through __init__/poll instead of stderr.
            self._record_failure(error)
        finally:
            for key in reversed(tuple(registered)):
                try:
                    self._unregister(key, registered)
                except BaseException as error:
                    if self._cleanup_failure is None:
                        self._cleanup_failure = error
                    self._record_failure(error)
            change = self._pending
            if change is not None and not change.done.is_set():
                change.error = self._failure or RuntimeError("全局热键服务已关闭。")
                change.done.set()
            self._finished.set()
            self._ready.set()

    def poll(self) -> list[str]:
        """Drain commands in arrival order, preserving separate key presses.

        MOD_NOREPEAT handles held-key repeats at registration; two independent
        presses must remain two commands, even within one polling interval.
        """
        if self._failure is not None:
            raise RuntimeError(f"全局热键不可用：{self._failure}") from self._failure
        if self._closed:
            return []
        actions: list[str] = []
        while True:
            try:
                actions.append(self._events.get_nowait())
            except queue.Empty:
                return actions

    def close(self) -> None:
        """Request WM_QUIT, join with a bound, and unregister on the owner thread.

        If startup times out inside an API call, the stop flag also prevents
        later registrations and makes the worker clean up as soon as it returns.
        A failed close may be retried; a successful close is a no-op thereafter.
        """
        with self._close_lock:
            if self._closed:
                return
            self._stopping.set()
            if self._thread.is_alive() and self._thread_id is not None:
                # A zero return is harmless if the worker exited concurrently;
                # the bounded join below checks the actual outcome.
                self._user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
            self._thread.join(_SHUTDOWN_TIMEOUT)
            if self._thread.is_alive():
                raise RuntimeError("全局热键线程未及时停止，请完全退出程序后重试。")
            self._closed = True
            if self._cleanup_failure is not None:
                raise RuntimeError(
                    f"全局热键注销失败：{self._cleanup_failure}；请完全退出程序。"
                ) from self._cleanup_failure
