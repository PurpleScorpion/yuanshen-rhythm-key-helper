"""Desktop point picker for the six-lane judgement line."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

import cv2

from . import PRODUCT_NAME
from .settings import DEFAULTS


class _Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in ("left", "top", "right", "bottom")]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("monitor", _Rect),
        ("work", _Rect),
        ("flags", ctypes.c_uint32),
    ]


def _work_area(root, screen_rect, *, adjust_scaling=True):
    """Use the target monitor's work area, including negative desktop positions."""
    fallback = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    if sys.platform != "win32":
        return fallback
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.MonitorFromRect.argtypes = [ctypes.POINTER(_Rect), ctypes.c_uint32]
    user.MonitorFromRect.restype = ctypes.c_void_p
    user.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
    user.GetMonitorInfoW.restype = ctypes.c_int
    x, y, width, height = screen_rect or (0, 0, 1, 1)
    bounds = _Rect(x, y, x + width, y + height)
    monitor = user.MonitorFromRect(ctypes.byref(bounds), 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
    if not monitor or not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return fallback
    # Tk 8.6 can inherit the primary monitor's text scale. Set it for this
    # independent root before its widgets/fonts are created on the game monitor.
    if adjust_scaling:
        try:
            shcore = ctypes.WinDLL("shcore")
            get_dpi = shcore.GetDpiForMonitor
            get_dpi.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            get_dpi.restype = ctypes.c_int32
            dpi_x, dpi_y = ctypes.c_uint32(), ctypes.c_uint32()
            if get_dpi(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0 and dpi_y.value:
                root.tk.call("tk", "scaling", dpi_y.value / 72)
        except (OSError, AttributeError):
            pass
    work = info.work
    return work.left, work.top, work.right - work.left, work.bottom - work.top


def _present(root, work_area=None):
    """Optionally center the root, then make a normal one-time focus request."""
    root.attributes("-topmost", True)
    root.deiconify()
    root.update_idletasks()
    root.lift()
    if sys.platform == "win32":
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        user.GetAncestor.restype = ctypes.c_void_p
        user.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
        user.GetWindowRect.restype = ctypes.c_int
        user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 5
        user.SetWindowPos.restype = ctypes.c_int
        user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user.SetForegroundWindow.restype = ctypes.c_int
        hwnd = user.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
        outer = _Rect()
        if work_area and user.GetWindowRect(hwnd, ctypes.byref(outer)):
            left, top, width, height = work_area
            x = left + max(0, (width - (outer.right - outer.left)) // 2)
            y = top + max(0, (height - (outer.bottom - outer.top)) // 2)
            # Native coordinates permit a monitor to the left/above the primary.
            user.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0015)  # NOSIZE|NOZORDER|NOACTIVATE
        if not user.SetForegroundWindow(hwnd):
            print(f"校准窗口已打开。请用 Alt+Tab 切到“{root.title()}”。", flush=True)
    elif work_area:
        left, top, width, height = work_area
        x = left + max(0, (width - root.winfo_width()) // 2)
        y = top + max(0, (height - root.winfo_height()) // 2)
        root.geometry(f"+{x}+{y}")


def choose_calibration(
    frame,
    settings: dict,
    save_points_callback: Callable[[list[tuple[float, float]]], str | None],
    controls=None,
    demo: bool = False,
    *,
    screen_rect: tuple[int, int, int, int] | None = None,
    parent=None,
) -> bool:
    """Pick A/L on the calling Tk thread. Pass its existing window as parent."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError("无法加载 Tk 校准窗口，请确认 Python 或便携包包含 Tcl/Tk。") from error
    if frame.ndim != 3 or frame.shape[2] not in (3, 4) or not frame.size:
        raise ValueError("校准需要一张有效的游戏截图。")
    # MSS screenshots may have a zeroed fourth byte; display their BGR channels.
    frame = frame[:, :, :3]
    if parent is None and sys.platform == "win32":
        from .windows_io import enable_dpi_awareness

        enable_dpi_awareness()
    try:
        root = tk.Toplevel(parent) if parent is not None else tk.Tk()
    except tk.TclError as error:
        raise RuntimeError(f"校准窗口启动失败，请检查 Tcl/Tk 资源：{error}") from error

    saved = False
    callback_errors: list[BaseException] = []
    timers: set[str] = set()
    finished = tk.BooleanVar(root, value=False)

    def finish(_event=None):
        finished.set(True)
        return "break"

    def guarded(callback):
        # Tk normally reports callback exceptions to the interpreter's main
        # window. Catch only this picker's callbacks and return them to its caller.
        def invoke(*args):
            try:
                return callback(*args)
            except BaseException as error:
                callback_errors.append(error)
                return finish()

        return invoke

    def schedule(delay, callback):
        def run():
            timers.discard(timer)
            if not finished.get():
                callback()

        timer = root.after(delay, guarded(run))
        timers.add(timer)
        return timer

    def cancel_timers():
        for timer in tuple(timers):
            root.after_cancel(timer)
            timers.discard(timer)

    topmost_timer = None

    def present(area=None):
        nonlocal topmost_timer
        _present(root, area)
        if topmost_timer in timers:
            root.after_cancel(topmost_timer)
            timers.discard(topmost_timer)
        topmost_timer = schedule(1000, lambda: root.attributes("-topmost", False))

    def on_destroy(event):
        if event.widget is root:
            cancel_timers()
            finish()

    try:
        root.bind("<Destroy>", on_destroy)
        root.withdraw()
        root.title(f"{PRODUCT_NAME} · {'校准练习' if demo else '校准'}")
        if parent is not None and screen_rect is None and parent.winfo_ismapped():
            screen_rect = (
                parent.winfo_rootx(),
                parent.winfo_rooty(),
                parent.winfo_width(),
                parent.winfo_height(),
            )
        work_area = _work_area(root, screen_rect, adjust_scaling=parent is None)
        factor = max(0.75, root.winfo_fpixels("1i") / 96)
        gap = max(6, round(8 * factor))
        keys = settings.get("keys", ("a", "s", "d", "j", "k", "l"))
        frame_height, frame_width = frame.shape[:2]
        points: list[tuple[float, float]] = []
        # The actual rounded image dimensions and margins are also used for
        # click conversion, including after resizing or letterboxing.
        image_box = (0, 0, 0, 0)
        photo = None
        hand = tk.StringVar(root)
        tip = tk.StringVar(root)

        body = ttk.Frame(root, padding=gap)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        heading = ttk.Label(body, textvariable=hand, font=("Microsoft YaHei UI", 13, "bold"))
        heading.grid(row=0, column=0, sticky="ew")
        message = ttk.Label(body, textvariable=tip, font=("Microsoft YaHei UI", 10))
        message.grid(row=1, column=0, sticky="ew", pady=(0, gap))
        canvas = tk.Canvas(
            body, width=1, height=1, background="#21252c", highlightthickness=0, cursor="crosshair"
        )
        canvas.grid(row=2, column=0, sticky="nsew")
        footer = ttk.Frame(body)
        footer.grid(row=3, column=0, sticky="e", pady=(gap, 0))

        def refresh_text(error: str = ""):
            prompts = (
                "第 1 步　点击最左侧 A 轨道的白色判定圆中心",
                "第 2 步　点击最右侧 L 轨道的白色判定圆中心",
                "核对判定线，然后点击“确认保存”结束校准",
            )
            hand.set(prompts[len(points)])
            hint = (
                "练习结果保存到 calibration-practice.json。"
                if demo
                else "请点击截图底部的白色圆圈，字母标签在圆圈下方。"
            )
            tip.set(error or hint)
            message.configure(foreground="#ae2630" if error else "#394652")
            confirm.state(["!disabled"] if len(points) == 2 else ["disabled"])
            reset_button.state(["!disabled"] if points else ["disabled"])

        def annotate():
            canvas.delete("marks")
            canvas.delete("guide")
            ox, oy, width, height = image_box
            if not width or not height:
                return

            def to_preview(point):
                x, y = point
                return (
                    ox + (x + 0.5) * width / frame_width - 0.5,
                    oy + (y + 0.5) * height / frame_height - 0.5,
                )

            if demo and len(points) < 2:
                end = 0 if not points else 5
                x, y = to_preview(
                    (DEFAULTS["lane_x"][end] * frame_width, DEFAULTS["hit_y"] * frame_height)
                )
                radius = max(round(12 * factor), round(25 * width / 1920))
                canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    outline="#ffc24e",
                    width=3,
                    dash=(5, 3),
                    tags="guide",
                )
                canvas.create_line(
                    x + 2 * radius,
                    y - 2 * radius,
                    x + radius * 0.72,
                    y - radius * 0.72,
                    fill="#ffc24e",
                    width=3,
                    arrow="last",
                    tags="guide",
                )
            if not points:
                return
            first = to_preview(points[0])
            marks = [(first, "A")]
            if len(points) == 2:
                last = to_preview(points[1])
                line_y = (first[1] + last[1]) / 2
                canvas.create_line(
                    first[0], line_y, last[0], line_y, fill="#49f2a7", width=2, tags="marks"
                )
                marks = [
                    ((first[0] + (last[0] - first[0]) * i / 5, line_y), key.upper())
                    for i, key in enumerate(keys)
                ]
            radius = max(5, round(6 * factor))
            for (x, y), label in marks:
                bbox = (x - radius, y - radius, x + radius, y + radius)
                canvas.create_oval(*bbox, outline="#122c23", width=4, tags="marks")
                canvas.create_oval(*bbox, outline="#49f2a7", width=2, tags="marks")
                canvas.create_text(
                    x,
                    y - radius - 2,
                    text=label,
                    fill="#49f2a7",
                    anchor="s",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    tags="marks",
                )

        @guarded
        def render(_event=None):
            nonlocal image_box, photo
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            if cw < 2 or ch < 2:
                return
            if int(message.cget("wraplength") or 0) != cw:
                heading.configure(wraplength=cw)
                message.configure(wraplength=cw)
            ratio = min(cw / frame_width, ch / frame_height)
            width = min(cw, max(1, round(frame_width * ratio)))
            height = min(ch, max(1, round(frame_height * ratio)))
            box = ((cw - width) // 2, (ch - height) // 2, width, height)
            if box == image_box:
                return
            interpolation = cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR
            preview = cv2.resize(frame, (width, height), interpolation=interpolation)
            ok, png = cv2.imencode(".png", preview, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            if not ok:
                raise RuntimeError("无法生成校准截图预览。")
            photo = tk.PhotoImage(master=root, data=png.tobytes(), format="png")
            canvas.delete("preview")
            canvas.create_image(box[0], box[1], anchor="nw", image=photo, tags="preview")
            image_box = box
            annotate()

        @guarded
        def click(event):
            ox, oy, width, height = image_box
            if len(points) == 2 or not (ox <= event.x < ox + width and oy <= event.y < oy + height):
                return
            x = (event.x - ox + 0.5) * frame_width / width - 0.5
            y = (event.y - oy + 0.5) * frame_height / height - 0.5
            points.append(
                (max(0.0, min(frame_width - 1.0, x)), max(0.0, min(frame_height - 1.0, y)))
            )
            refresh_text()
            annotate()

        @guarded
        def reset(_event=None):
            points.clear()
            refresh_text()
            annotate()
            return "break"

        @guarded
        def save(_event=None):
            nonlocal saved
            if len(points) == 2 and not saved:
                error = save_points_callback(points.copy())
                if error is None:
                    saved = True
                    finish()
                else:
                    refresh_text(str(error))
            return "break"

        def poll_controls():
            commands = controls.poll()
            if any(command in ("stop", "shutdown", "toggle") for command in commands):
                finish()
            else:
                if "calibrate" in commands:
                    present()
                schedule(35, poll_controls)

        confirm = ttk.Button(footer, text="确认保存 (Enter)", command=save)
        confirm.grid(row=0, column=0, padx=(0, gap))
        reset_button = ttk.Button(footer, text="重选 (R)", command=reset)
        reset_button.grid(row=0, column=1, padx=(0, gap))
        ttk.Button(footer, text="取消 (Esc)", command=finish).grid(row=0, column=2)
        refresh_text()
        root.protocol("WM_DELETE_WINDOW", finish)
        root.bind("<Return>", save)
        root.bind("<Escape>", finish)
        root.bind("<Key-r>", reset)
        root.bind("<Key-R>", reset)
        canvas.bind("<Configure>", render)
        canvas.bind("<Button-1>", click)
        root.update_idletasks()

        max_width = max(1, work_area[2] - round(56 * factor))
        max_height = max(1, work_area[3] - round(86 * factor))
        extra_height = root.winfo_reqheight() - canvas.winfo_reqheight()
        ratio = min(
            1.0, (max_width - 2 * gap) / frame_width, (max_height - extra_height) / frame_height
        )
        width = min(max_width, max(root.winfo_reqwidth(), round(frame_width * ratio) + 2 * gap))
        height = min(max_height, max(extra_height + 1, round(frame_height * ratio) + extra_height))
        root.geometry(f"{width}x{height}")
        root.minsize(min(max_width, round(400 * factor)), min(max_height, round(240 * factor)))
        present(work_area)
        render()
        if controls is not None:
            schedule(35, poll_controls)
        if not finished.get():
            root.wait_variable(finished)
        if callback_errors:
            raise callback_errors[0]
        return saved
    except tk.TclError as error:
        raise RuntimeError(f"校准窗口显示失败：{error}") from error
    finally:
        # A shared parent may have independent status/shutdown timers. An
        # externally destroyed parent has already destroyed this child as well.
        cancel_timers()
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass  # The Tk application was closed while waiting for this picker.
