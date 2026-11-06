"""First-use declaration and read-only notice viewer."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from . import PRODUCT_NAME

PROJECT_URL = "https://github.com/PurpleScorpion/yuanshen-rhythm-key-helper"
CLAUSES = (
    "本程序仅供学习和交流使用，严禁用于商业用途。",
    "为了游戏平衡，游戏内严禁在传说模式使用本程序，否则后果自负。"
    "（传说模式会随机故意按错几个键。）",
    "游戏中请使用「垂直模式」。界面样式请勿使用购买的其他样式，请使用初始版本的「轻漾涟漪」。",
    "「设置 - 特化」中的四个选项请勿勾选，包括降低难度的选项。"
    "（做这个的时候压根就没看到有这个功能。）",
)


def show_notice(parent=None, *, required: bool = False) -> bool:
    """Return True only when the required notice's 我接受 button is invoked.

    A standalone window waits until dismissed. Reviewing from the main window
    opens a modeless child and returns False immediately, leaving its worker
    and the parent's shutdown loop free to run. This function writes no state.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError("无法加载使用声明，请检查 Tcl/Tk 资源。") from error

    if parent is not None and not required:
        existing = parent.children.get("usage_notice")
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            return False
    if parent is None and sys.platform == "win32":
        from .windows_io import enable_dpi_awareness

        enable_dpi_awareness()
    try:
        window = (
            tk.Tk()
            if parent is None
            else tk.Toplevel(parent, name="required_notice" if required else "usage_notice")
        )
    except tk.TclError as error:
        raise RuntimeError(f"使用声明窗口启动失败：{error}") from error

    from .calibration_ui import _work_area
    from .main_ui import _LogScroll

    accepted = False
    keep_open = False
    try:
        window.withdraw()
        window.title(f"{PRODUCT_NAME} · 使用声明")
        window.configure(background="#f4f6f7")
        target_rect = None
        if parent is not None:
            window.transient(parent)
            if parent.winfo_ismapped():
                target_rect = (
                    parent.winfo_rootx(),
                    parent.winfo_rooty(),
                    parent.winfo_width(),
                    parent.winfo_height(),
                )
        elif sys.platform == "win32":
            folder = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            icon = folder / "assets" / "rhythm.ico"
            if icon.is_file():
                try:
                    window.iconbitmap(default=str(icon))
                except tk.TclError:
                    pass
        left, top, work_width, work_height = _work_area(
            window, target_rect, adjust_scaling=parent is None
        )
        scale = max(0.75, window.winfo_fpixels("1i") / 96)
        pad = max(8, round(18 * scale))
        gap = max(4, round(8 * scale))
        width = max(1, min(round(640 * scale), work_width - 2 * pad))
        height = max(1, min(round(500 * scale), work_height - 4 * pad))
        cx = target_rect[0] + target_rect[2] // 2 if target_rect else left + work_width // 2
        cy = target_rect[1] + target_rect[3] // 2 if target_rect else top + work_height // 2
        x = max(left, min(cx - width // 2, left + work_width - width))
        y = max(top, min(cy - height // 2, top + work_height - height - 2 * pad))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(min(width, round(340 * scale)), min(height, round(260 * scale)))

        style = ttk.Style(window)
        if parent is None and "clam" in style.theme_names():
            style.theme_use("clam")
        font = ("Microsoft YaHei UI", 11)
        style.configure("Notice.TButton", font=(font[0], 10), padding=(gap + 4, gap))
        style.configure(
            "Accept.Notice.TButton",
            font=(font[0], 10, "bold"),
            foreground="white",
            background="#157162",
            bordercolor="#157162",
            lightcolor="#157162",
            darkcolor="#157162",
        )
        style.map(
            "Accept.Notice.TButton",
            background=[("pressed", "#0e5348"), ("active", "#125f53")],
            foreground=[("!disabled", "white")],
        )
        body = tk.Frame(window, background="#f4f6f7", padx=pad, pady=pad)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        tk.Label(
            body,
            text="使用声明",
            background="#f4f6f7",
            foreground="#1d3037",
            font=(font[0], 18, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        if required:
            tk.Label(
                body,
                text="请阅读以下四点，接受后继续使用。",
                background="#f4f6f7",
                foreground="#53666d",
                font=(font[0], 10),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", pady=(0, gap // 2))
        card = tk.Frame(
            body, background="white", highlightbackground="#d9e1e3", highlightthickness=1
        )
        card.grid(row=2, column=0, sticky="nsew", pady=(gap, 0))
        text = tk.Text(
            card,
            name="clauses",
            width=1,
            height=1,
            wrap="char",
            font=font,
            background="white",
            foreground="#23373c",
            relief="flat",
            highlightthickness=0,
            padx=gap + 4,
            pady=gap,
            cursor="arrow",
            spacing2=max(1, round(2 * scale)),
        )
        _LogScroll(card, text, scale)
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("number", font=(font[0], 11, "bold"), foreground="#157162")
        text.tag_configure("paragraph", spacing3=gap)
        text.tag_configure("link", foreground="#12685c", underline=True)
        for i, clause in enumerate(CLAUSES, 1):
            text.insert("end", f"{i}. ", ("number", "paragraph"))
            text.insert("end", clause + "\n", "paragraph")
        text.insert("end", "本软件开源，项目地址为\n")
        text.insert("end", PROJECT_URL, "link")
        text.configure(state="disabled")

        def open_link(_event=None):
            try:
                opened = webbrowser.open_new_tab(PROJECT_URL)
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                from tkinter import messagebox

                messagebox.showinfo(
                    "项目地址", "未能打开浏览器，请复制声明中的项目地址。", parent=window
                )
            return "break"

        text.tag_bind("link", "<Enter>", lambda _event: text.configure(cursor="hand2"))
        text.tag_bind("link", "<Leave>", lambda _event: text.configure(cursor="arrow"))
        text.tag_bind("link", "<Button-1>", open_link)

        def dismiss(_event=None):
            window.destroy()
            return "break"

        def accept():
            nonlocal accepted
            accepted = True
            window.destroy()

        actions = tk.Frame(body, background="#f4f6f7")
        actions.grid(row=3, column=0, sticky="e", pady=(gap, 0))
        if required:
            ttk.Button(
                actions, name="decline", text="退出", style="Notice.TButton", command=dismiss
            ).grid(row=0, column=0, padx=(0, gap))
            accept_button = ttk.Button(
                actions, name="accept", text="我接受", style="Accept.Notice.TButton", command=accept
            )
            accept_button.grid(row=0, column=1)
            # Enter must never accept the initial declaration, including when
            # keyboard navigation has focused this button. Space still invokes
            # a deliberately focused button for keyboard-only accessibility.
            accept_button.bind("<Return>", lambda _event: "break")
            accept_button.bind("<KP_Enter>", lambda _event: "break")
        else:
            ttk.Button(
                actions, name="close_notice", text="关闭", style="Notice.TButton", command=dismiss
            ).grid(row=0, column=0)
        window.protocol("WM_DELETE_WINDOW", dismiss)
        window.bind("<Escape>", dismiss)
        window.deiconify()
        window.lift()
        text.focus_set()
        if parent is not None and not required:
            keep_open = True
            return False
        if parent is not None:
            window.grab_set()
        window.wait_window(window)
        return accepted
    except tk.TclError as error:
        raise RuntimeError(f"使用声明窗口显示失败：{error}") from error
    finally:
        if not keep_open:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass  # The user may already have closed the standalone root.
