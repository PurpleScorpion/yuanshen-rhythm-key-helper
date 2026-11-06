"""Non-blocking Tk shortcut editor. The session registers and persists the result."""

from __future__ import annotations

from . import PRODUCT_NAME
from .keybinds import DEFAULT_HOTKEYS, canonical, display, from_event


class HotkeyEditor:
    def __init__(self, parent, bindings, on_apply, on_close):
        import tkinter as tk
        from tkinter import ttk

        self.on_apply = on_apply
        self.on_close = on_close
        self.pending = False
        self.closed = False
        self.listening: str | None = None
        self.values = {name: canonical(value) for name, value in bindings.items()}
        self.window = window = tk.Toplevel(parent, name="hotkey_editor")
        window.withdraw()
        try:
            window.title(f"{PRODUCT_NAME} · 快捷键设置")
            window.transient(parent)
            window.resizable(False, False)
            window.configure(background="#f4f6f7")
            scale = max(0.75, parent.winfo_fpixels("1i") / 96)
            pad = max(10, round(18 * scale))
            gap = max(5, round(8 * scale))
            font = ("Microsoft YaHei UI", 10)
            body = tk.Frame(window, background="#f4f6f7", padx=pad, pady=pad)
            body.pack(fill="both", expand=True)
            body.columnconfigure(1, weight=1)
            tk.Label(
                body,
                text="快捷键设置",
                background="#f4f6f7",
                foreground="#1d3037",
                font=(font[0], 16, "bold"),
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="ew")
            tk.Label(
                body,
                text="点击要更改的键位，再按新快捷键。没有小键盘时，可以用 F8 或 Ctrl+Shift+9。",
                background="#f4f6f7",
                foreground="#53666d",
                justify="left",
                font=font,
                wraplength=round(385 * scale),
                anchor="w",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(gap // 2, gap))

            self.key_buttons = {}
            for row, (name, title) in enumerate(
                (("toggle", "启停演奏"), ("calibrate", "游戏校准")), 2
            ):
                tk.Label(
                    body,
                    text=title,
                    font=(font[0], 10, "bold"),
                    background="#f4f6f7",
                    foreground="#1d3037",
                    anchor="w",
                ).grid(row=row, column=0, sticky="w", padx=(0, pad), pady=gap // 2)
                button = ttk.Button(
                    body,
                    name=f"{name}_key",
                    style="Helper.TButton",
                    width=23,
                    command=lambda action=name: self.record(action),
                )
                button.grid(row=row, column=1, sticky="ew", pady=gap // 2)
                self.key_buttons[name] = button

            self.notice = tk.Label(
                body,
                name="notice",
                text="更改后点击“应用”即可生效。",
                anchor="w",
                justify="left",
                background="#f4f6f7",
                foreground="#53666d",
                font=font,
                wraplength=round(385 * scale),
            )
            self.notice.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(gap, gap))
            actions = tk.Frame(body, background="#f4f6f7")
            actions.grid(row=5, column=0, columnspan=2, sticky="ew")
            actions.columnconfigure(1, weight=1)
            self.defaults = ttk.Button(
                actions,
                name="restore_defaults",
                text="恢复默认",
                style="Helper.TButton",
                command=self.restore_defaults,
            )
            self.defaults.grid(row=0, column=0, sticky="w")
            self.cancel_button = ttk.Button(
                actions, name="cancel", text="取消", style="Helper.TButton", command=self.close
            )
            self.cancel_button.grid(row=0, column=2, padx=(gap, gap))
            self.apply_button = ttk.Button(
                actions,
                name="apply",
                text="应用",
                style="Primary.Helper.TButton",
                command=self.submit,
            )
            self.apply_button.grid(row=0, column=3)
            self.refresh()
            window.bind("<KeyPress>", self.key_event)
            window.protocol("WM_DELETE_WINDOW", self.close)
            window.update_idletasks()
            width, height = window.winfo_reqwidth(), window.winfo_reqheight()
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
            # Let translated validation errors increase the requested height.
            window.geometry(f"+{x}+{y}")
            window.deiconify()
            window.grab_set()
            window.focus_set()
        except Exception:
            window.destroy()
            raise

    def refresh(self):
        for name, button in self.key_buttons.items():
            selected = name == self.listening
            button.configure(
                text="请按新的快捷键…" if selected else display(self.values[name]),
                style="Primary.Helper.TButton" if selected else "Helper.TButton",
            )
            button.state(["disabled"] if self.pending else ["!disabled"])
        self.defaults.state(["disabled"] if self.pending else ["!disabled"])
        self.cancel_button.state(["disabled"] if self.pending else ["!disabled"])
        valid = self.values["toggle"] != self.values["calibrate"]
        can_apply = valid and not self.pending and self.listening is None
        self.apply_button.state(["!disabled"] if can_apply else ["disabled"])

    def hint(self, message: str, *, error: bool = False):
        self.notice.configure(text=message, foreground="#aa3438" if error else "#53666d")

    def record(self, name):
        if self.pending:
            return
        self.listening = name
        self.hint("请直接按新快捷键，Esc 取消本次录入。")
        self.refresh()
        # The toplevel receives the next key directly, before any button binding.
        self.window.focus_set()

    def capture(self, text):
        """Handle a physical key or an already-registered WM_HOTKEY shortcut."""
        if self.closed or self.pending or self.listening is None:
            return
        try:
            value = canonical(text)
        except ValueError as error:
            self.hint(str(error), error=True)
            return
        self.values[self.listening] = value
        self.listening = None
        if self.values["toggle"] == self.values["calibrate"]:
            self.hint("两个操作需要不同的快捷键，请再更改另一项。", error=True)
        else:
            self.hint("已录入，点击“应用”保存。")
        self.refresh()

    def key_event(self, event):
        if self.pending:
            return "break"
        if event.keysym == "Escape":
            if self.listening is None:
                self.close()
            else:
                self.listening = None
                self.hint("已取消本次录入。")
                self.refresh()
            return "break"
        if self.listening is None:
            return None
        try:
            value = from_event(event)
        except ValueError as error:
            self.hint(str(error), error=True)
        else:
            if value is not None:
                self.capture(value)
        return "break"

    def restore_defaults(self):
        if self.pending:
            return
        self.listening = None
        self.values = dict(DEFAULT_HOTKEYS)
        self.hint("已填入默认快捷键，点击“应用”保存。")
        self.refresh()

    def submit(self):
        if (
            self.pending
            or self.listening is not None
            or self.values["toggle"] == self.values["calibrate"]
        ):
            return
        self.pending = True
        self.hint("正在注册快捷键…")
        self.refresh()
        try:
            self.on_apply(dict(self.values))
        except (OSError, ValueError, RuntimeError) as error:
            self.complete(False, str(error))

    def complete(self, success, message):
        if self.closed:
            return
        self.pending = False
        if success:
            self.close()
        else:
            self.hint(message, error=True)
            self.refresh()

    def close(self, *, force=False):
        if self.closed or (self.pending and not force):
            return
        self.closed = True
        try:
            self.window.destroy()
        finally:
            self.on_close()
