"""Desktop controls for the rhythm helper. Tk stays on the calling thread."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import PRODUCT_NAME
from .keybinds import DEFAULT_HOTKEYS, display

_BG = "#f4f6f7"
_PAPER = "#ffffff"
_INK = "#1d3037"
_MUTED = "#53666d"
_BORDER = "#d9e1e3"
_TEAL = "#157162"
_STATES = {
    "idle": ("待启动", "#576b73"),
    "waiting": ("等待原神", "#895b17"),
    "running": ("运行中", "#146849"),
    "paused": ("已停止", "#576b73"),
    "error": ("遇到问题", "#aa3438"),
}


class _LogScroll:
    """Small proportional log thumb with a wider pointer hit target."""

    def __init__(self, parent, text, scale):
        import tkinter as tk

        self.text = text
        self.scale = scale
        self.first, self.last = 0.0, 1.0
        self.hover = False
        self.drag_offset = None
        self.canvas = tk.Canvas(
            parent,
            name="log_scrollbar",
            width=max(10, round(14 * scale)),
            height=1,
            background=_PAPER,
            borderwidth=0,
            highlightthickness=0,
            takefocus=False,
        )
        self.canvas.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.canvas.bind("<Enter>", lambda _event: self.highlight(True))
        self.canvas.bind("<Leave>", lambda _event: self.highlight(False))
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<MouseWheel>", self.wheel)
        text.configure(yscrollcommand=self.set)

    def metrics(self):
        pad = max(2, round(3 * self.scale))
        available = max(1, self.canvas.winfo_height() - 2 * pad)
        visible = min(1.0, max(0.0, self.last - self.first))
        length = min(available, max(round(24 * self.scale), available * visible))
        travel = available - length
        top = pad + (travel * self.first / (1.0 - visible) if visible < 1.0 else 0)
        return pad, visible, length, travel, top

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def highlight(self, active):
        self.hover = active
        self.draw()

    def draw(self):
        canvas = self.canvas
        canvas.delete("bar")
        pad, visible, length, _travel, top = self.metrics()
        if visible >= 0.9999 or canvas.winfo_height() <= 2 * pad:
            return
        x = canvas.winfo_width() / 2
        line_width = max(
            3, round((7 if self.hover or self.drag_offset is not None else 5) * self.scale)
        )
        radius = line_width / 2
        canvas.create_line(
            x,
            pad + radius,
            x,
            canvas.winfo_height() - pad - radius,
            fill="#edf3f2",
            capstyle="round",
            width=line_width,
            tags="bar",
        )
        color = (
            "#478b81" if self.drag_offset is not None else "#7ca9a2" if self.hover else "#afc7c3"
        )
        canvas.create_line(
            x,
            top + radius,
            x,
            top + length - radius,
            fill=color,
            capstyle="round",
            width=line_width,
            tags=("bar", "thumb"),
        )

    def press(self, event):
        _pad, _visible, length, travel, top = self.metrics()
        if travel > 0:
            self.drag_offset = event.y - top if top <= event.y <= top + length else length / 2
            self.drag(event)
            self.draw()

    def drag(self, event):
        if self.drag_offset is None:
            return
        pad, visible, _length, travel, _top = self.metrics()
        if travel > 0:
            ratio = min(1.0, max(0.0, (event.y - self.drag_offset - pad) / travel))
            self.text.yview_moveto(ratio * (1 - visible))

    def release(self, _event):
        self.drag_offset = None
        self.draw()

    def wheel(self, event):
        self.text.event_generate("<MouseWheel>", delta=event.delta)
        return "break"


class _MainWindow:
    def __init__(self, root, session, dry_run: bool):
        import tkinter as tk
        from tkinter import ttk

        from .calibration_ui import _work_area

        self.root = root
        self.session = session
        self.dry_run = dry_run
        self.state = "idle"
        self.ready = False
        self.calibrating = False
        self.closing = False
        self.finished = False
        self.backend_ended = False
        self.mouse_action = None
        self.picker_debounce_until = 0.0
        self.drain_failed = False
        self.editor = None
        self.bindings = dict(session.settings.get("hotkeys", DEFAULT_HOTKEYS))
        self.command_layout = None

        root.withdraw()
        root.title(PRODUCT_NAME)
        assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets"
        if sys.platform == "win32" and (assets / "rhythm.ico").is_file():
            try:
                root.iconbitmap(default=str(assets / "rhythm.ico"))
            except tk.TclError:
                pass
        root.configure(background=_BG)
        left, top, work_width, work_height = _work_area(root, None)
        scale = max(0.75, root.winfo_fpixels("1i") / 96)
        self.pad = max(8, round(18 * scale))
        small = max(4, round(8 * scale))
        self.gap = small
        width = min(round(680 * scale), max(1, work_width - round(40 * scale)))
        height = min(round(495 * scale), max(1, work_height - round(80 * scale)))
        x = max(0, left + (work_width - width) // 2)
        y = max(0, top + (work_height - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min(width, round(460 * scale)), min(height, round(360 * scale)))

        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        font = ("Microsoft YaHei UI", 10)
        style.configure(
            "Helper.TButton",
            font=font,
            padding=(small + 2, small),
            background=_PAPER,
            foreground=_INK,
            bordercolor=_BORDER,
            lightcolor=_BORDER,
            darkcolor=_BORDER,
        )
        style.map(
            "Helper.TButton",
            background=[("pressed", "#dce8e4"), ("active", "#edf4f2")],
            foreground=[("disabled", "#8a9598")],
        )
        style.configure(
            "Primary.Helper.TButton",
            font=(font[0], 10, "bold"),
            background=_TEAL,
            foreground="white",
            bordercolor=_TEAL,
            lightcolor=_TEAL,
            darkcolor=_TEAL,
        )
        style.map(
            "Primary.Helper.TButton",
            background=[("disabled", "#e1e8e7"), ("pressed", "#0e5348"), ("active", "#125f53")],
            foreground=[("disabled", "#647773"), ("!disabled", "white")],
        )

        body = tk.Frame(root, background=_BG, padx=self.pad, pady=self.pad)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        header = tk.Frame(body, background=_BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, small + 2))
        header.columnconfigure(0, weight=1)
        title = tk.Label(
            header,
            text=PRODUCT_NAME,
            background=_BG,
            foreground=_INK,
            font=(font[0], 20, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")
        mode_badge = tk.Label(
            header,
            text="仅识别" if dry_run else "自动按键",
            background="#e0eeeb",
            foreground="#215d54",
            padx=small,
            pady=max(2, small // 2),
            font=font,
        )
        mode_badge.grid(row=0, column=1, sticky="e")
        self.settings_button = ttk.Button(
            header,
            name="hotkey_settings",
            text="快捷键设置",
            style="Helper.TButton",
            command=self.open_hotkey_editor,
        )
        self.settings_button.grid(row=0, column=2, sticky="e", padx=(small, 0))
        title_width = title.winfo_reqwidth()

        def fit_title(event):
            available = (
                event.width
                - mode_badge.winfo_reqwidth()
                - self.settings_button.winfo_reqwidth()
                - small
            )
            size = min(20, max(12, 20 * available // title_width))
            title.configure(font=(font[0], size, "bold"))

        header.bind("<Configure>", fit_title)

        card = tk.Frame(body, background=_PAPER, highlightbackground=_BORDER, highlightthickness=1)
        self.card = card
        card.grid(row=1, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        self.state_label = tk.Label(
            card,
            text="待启动",
            font=(font[0], 14, "bold"),
            background=_PAPER,
            foreground=_STATES["idle"][1],
            anchor="w",
        )
        self.state_label.grid(row=0, column=0, sticky="ew", padx=self.pad, pady=(small + 2, 0))
        self.detail = tk.Label(
            card,
            text=f"点击开始，或在游戏中按 {display(self.bindings['toggle'])}。",
            font=font,
            background=_PAPER,
            foreground=_MUTED,
            anchor="w",
            justify="left",
            wraplength=width - 4 * self.pad,
        )
        self.detail.grid(row=1, column=0, sticky="ew", padx=self.pad, pady=(2, small))
        card.bind("<Configure>", lambda event: self.layout_commands(event.width))
        commands = tk.Frame(card, background=_PAPER)
        commands.grid(row=2, column=0, sticky="w", padx=self.pad, pady=(0, small + 2))
        self.primary = ttk.Button(
            commands, style="Primary.Helper.TButton", command=self.primary_action
        )
        self.primary.grid(row=0, column=0, padx=(0, small))
        # Remember what the user clicked. Bringing this GUI forward can pause
        # the game before the mouse is released and the button command runs.
        self.primary.bind("<ButtonPress-1>", self.remember_mouse_action)
        self.primary.bind(
            "<ButtonRelease-1>", lambda _event: root.after_idle(self.forget_mouse_action)
        )
        self.calibrate_button = ttk.Button(
            commands,
            text=f"游戏校准 ({display(self.bindings['calibrate'])})",
            style="Helper.TButton",
            command=lambda: self.command("calibrate"),
        )
        self.calibrate_button.grid(row=0, column=1, padx=(0, small))
        self.tutorial = ttk.Button(
            commands,
            text="校准教程",
            style="Helper.TButton",
            command=lambda: self.command("tutorial"),
        )
        self.tutorial.grid(row=0, column=2)

        tk.Label(
            body,
            text="近期动作与日志",
            font=(font[0], 11, "bold"),
            anchor="w",
            background=_BG,
            foreground=_INK,
        ).grid(row=2, column=0, sticky="ew", pady=(small + 2, small // 2))
        history = tk.Frame(
            body, background=_PAPER, highlightbackground=_BORDER, highlightthickness=1
        )
        history.grid(row=3, column=0, sticky="nsew")
        self.log = tk.Text(
            history,
            height=5,
            width=1,
            font=font,
            background=_PAPER,
            foreground=_INK,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            padx=small,
            pady=small,
            spacing1=1,
            state="disabled",
        )
        self.log_scroll = _LogScroll(history, self.log, scale)
        self.log.pack(side="left", fill="both", expand=True)
        footer_bar = tk.Frame(body, background=_BG)
        footer_bar.grid(row=4, column=0, sticky="ew", pady=(small, 0))
        footer_bar.columnconfigure(0, weight=1)
        self.footer = tk.Label(
            footer_bar,
            font=(font[0], 9),
            background=_BG,
            foreground=_MUTED,
            anchor="w",
            justify="left",
            wraplength=width - 2 * self.pad,
        )
        self.footer.grid(row=0, column=0, sticky="ew")
        self.footer.bind("<Configure>", lambda event: self.footer.configure(wraplength=event.width))
        tk.Button(
            footer_bar,
            name="view_notice",
            text="使用声明",
            command=self.open_notice,
            font=(font[0], 9, "underline"),
            cursor="hand2",
            foreground=_TEAL,
            background=_BG,
            activeforeground="#0e5348",
            activebackground="#e5efec",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightcolor=_TEAL,
            highlightbackground=_BG,
            padx=small,
            pady=1,
        ).grid(row=0, column=1, sticky="e", padx=(small, 0))
        self.refresh_bindings()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-c>", self.copy_or_close)
        root.bind("<Control-C>", self.copy_or_close)
        self.refresh_controls()
        root.deiconify()

    def primary_command(self):
        return "stop" if self.state in ("waiting", "running") else "start"

    def remember_mouse_action(self, _event):
        self.mouse_action = self.primary_command()

    def forget_mouse_action(self):
        self.mouse_action = None

    def primary_action(self):
        action = self.mouse_action or self.primary_command()
        self.mouse_action = None
        self.command(action)

    def refresh_controls(self):
        enabled = self.ready and not (
            self.closing or self.calibrating or self.backend_ended or self.editor
        )
        verb = "识别" if self.dry_run else "演奏"
        primary_text = ("停止" if self.primary_command() == "stop" else "开始") + verb
        self.primary.configure(text=primary_text)
        self.primary.state(["!disabled"] if enabled else ["disabled"])
        picker_enabled = enabled and time.monotonic() >= self.picker_debounce_until
        for button in (self.calibrate_button, self.tutorial):
            button.state(["!disabled"] if picker_enabled else ["disabled"])
        self.settings_button.state(["!disabled"] if enabled else ["disabled"])

    def refresh_bindings(self):
        toggle, calibrate = (display(self.bindings[name]) for name in ("toggle", "calibrate"))
        self.calibrate_button.configure(text=f"游戏校准 ({calibrate})")
        hint = f"{toggle} 启停    ·    {calibrate} 游戏校准"
        if any("NumPad" in value for value in self.bindings.values()):
            hint += "    ·    小键盘需开启 Num Lock"
        self.footer.configure(text=hint)
        self.root.after_idle(self.layout_commands)

    def layout_commands(self, width=None):
        available = max(40, (width or self.card.winfo_width()) - 2 * self.pad - 4)
        self.detail.configure(wraplength=available)
        first = self.primary.winfo_reqwidth()
        second = self.calibrate_button.winfo_reqwidth()
        third = self.tutorial.winfo_reqwidth()
        if first + second + third + 2 * self.gap <= available:
            layout = "single"
        elif first + second + self.gap <= available:
            layout = "tutorial_below"
        else:
            layout = "calibration_below"
        if layout == self.command_layout:
            return
        self.command_layout = layout
        # Keep a long modifier combination visible even in the smallest window.
        if layout == "calibration_below":
            self.calibrate_button.grid_configure(row=1, column=0, columnspan=2, pady=(self.gap, 0))
            self.tutorial.grid_configure(row=0, column=1, pady=0)
        else:
            self.calibrate_button.grid_configure(row=0, column=1, columnspan=1, pady=0)
            below = layout == "tutorial_below"
            self.tutorial.grid_configure(
                row=int(below), column=0 if below else 2, pady=(self.gap if below else 0, 0)
            )

    def open_hotkey_editor(self):
        if self.closing or self.calibrating or self.backend_ended or not self.ready:
            return
        if self.editor is not None:
            self.editor.window.lift()
            return
        from .hotkey_editor import HotkeyEditor

        self.session.begin_hotkey_edit()
        try:
            self.editor = HotkeyEditor(
                self.root, self.bindings, self.session.set_hotkeys, self.editor_closed
            )
        except Exception as error:
            self.session.end_hotkey_edit()
            self.show_error(f"无法打开快捷键设置：{error}")
        self.refresh_controls()

    def open_notice(self):
        if self.closing or self.calibrating or self.editor:
            return
        from .notice_ui import show_notice

        if self.state in ("running", "waiting"):
            self.command("stop")
        try:
            show_notice(self.root)
        except RuntimeError as error:
            self.show_error(error)

    def editor_closed(self):
        self.editor = None
        self.session.end_hotkey_edit()
        self.refresh_controls()

    def hotkeys_changed(self, success, message, bindings):
        self.bindings = dict(bindings)
        self.refresh_bindings()
        self.append_logs([message])
        if self.editor is not None:
            self.editor.complete(success, message)
        if success and not self.closing:
            self.show_status("paused", message)

    def show_status(self, state, detail):
        if state not in _STATES:
            return
        self.state = state
        label, color = _STATES[state]
        self.state_label.configure(text=label, foreground=color)
        self.detail.configure(text=detail)
        self.refresh_controls()

    def append_logs(self, lines):
        if not lines:
            return
        at_bottom = self.log.yview()[1] >= 0.995
        stamp = time.strftime("%H:%M:%S")
        entries = [
            f"{stamp}  {line}\n" for text in lines for line in str(text).splitlines() if line
        ]
        if not entries:
            return
        self.log.configure(state="normal")
        self.log.insert("end", "".join(entries))
        last_line = int(self.log.index("end-1c").split(".")[0])
        if last_line > 251:
            self.log.delete("1.0", f"{last_line - 250}.0")
        self.log.configure(state="disabled")
        if at_bottom:
            self.log.see("end")

    def show_error(self, error):
        detail = str(error) or "会话启动失败。"
        self.show_status("error", detail)
        self.append_logs([detail])

    def command(self, command):
        if self.closing or self.calibrating or self.backend_ended or self.editor or not self.ready:
            return
        try:
            self.session.command(command)
        except (OSError, RuntimeError, ValueError) as error:
            self.show_error(error)
            return
        if command == "start":
            self.show_status(
                "waiting", "正在请求启动演奏。" if not self.dry_run else "正在请求开始识别。"
            )
        elif command in ("calibrate", "tutorial"):
            self.picker_debounce_until = time.monotonic() + 0.35
            self.refresh_controls()

    def open_picker(self, picker):
        if self.closing or self.backend_ended or self.calibrating or self.editor:
            return
        self.calibrating = True
        self.refresh_controls()
        try:
            self.root.update_idletasks()
            picker()
        except KeyboardInterrupt:
            self.close()
        except (OSError, RuntimeError, ValueError) as error:
            self.show_error(error)
        finally:
            self.calibrating = False
            self.refresh_controls()

    def close(self, _event=None):
        if not self.closing:
            self.closing = True
            self.show_status("paused", "正在停止演奏并释放按键，随后关闭窗口。")
            self.session.close()
            if self.editor:
                self.editor.close(force=True)
        return "break"

    def copy_or_close(self, event):
        if event.widget is self.log:
            selected = self.log.tag_ranges("sel")
            if selected:
                self.root.clipboard_clear()
                self.root.clipboard_append(self.log.get(*selected))
            return "break"
        return self.close()

    def pump(self):
        try:
            events = [] if self.drain_failed else self.session.drain()
        except (OSError, RuntimeError) as error:
            self.drain_failed = True
            self.backend_ended = True
            self.show_error(error)
            self.session.close()
            events = []
        lines = []
        for kind, payload in events:
            if kind == "log":
                lines.append(payload)
            elif kind == "status" and not self.closing and not self.backend_ended:
                self.show_status(*payload)
            elif kind == "calibration":
                self.open_picker(payload)
            elif kind == "hotkeys":
                self.hotkeys_changed(*payload)
            elif kind == "hotkey_capture" and self.editor and not self.closing:
                self.editor.capture(payload)
            elif kind == "exit":
                self.backend_ended = True
                if self.editor:
                    self.editor.close(force=True)
                self.refresh_controls()
                if payload and not self.closing:
                    self.show_error(payload)
                else:
                    self.close()
        self.append_logs(lines)
        if self.closing and not self.session.alive and not self.calibrating:
            self.finished = True
            self.root.quit()
        else:
            self.refresh_controls()
            self.root.after(60, self.pump)

    def run(self):
        try:
            self.session.start()
            self.ready = True
        except (OSError, RuntimeError, ValueError) as error:
            self.backend_ended = True
            self.show_error(error)
        self.refresh_controls()
        self.root.after(0, self.pump)
        while not self.finished:
            try:
                self.root.mainloop()
            except KeyboardInterrupt:
                self.close()


def run_ui(settings, path, *, dry_run: bool = False) -> None:
    try:
        import tkinter as tk
    except ImportError as error:
        raise RuntimeError("无法加载桌面窗口，请检查 Tcl/Tk 资源。") from error
    if sys.platform == "win32":
        from .windows_io import enable_dpi_awareness

        enable_dpi_awareness()
    from .gui_session import GuiSession

    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError(f"桌面窗口启动失败，请检查 Tcl/Tk 资源：{error}") from error
    try:
        session = GuiSession(settings, path, dry_run=dry_run)
        session.parent = root
        window = _MainWindow(root, session, dry_run)
        try:
            window.run()
        finally:
            session.close()
            # Normal closure leaves through pump() only after the worker exits.
            # Keep the same ordering if Tk or the caller interrupts startup.
            while session.alive:
                try:
                    root.update()
                except (tk.TclError, KeyboardInterrupt):
                    pass
                time.sleep(0.02)
    finally:
        root.destroy()
