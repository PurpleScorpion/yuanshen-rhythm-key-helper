import sys
import traceback

from rhythm_helper import PRODUCT_NAME


def connect_cli_output():
    """Windowed builds still support --inspect, shell redirection and --help."""
    import ctypes
    import os

    kernel = ctypes.windll.kernel32
    if sys.stdout is None:
        kernel.AttachConsole(ctypes.c_uint32(-1))
    for fd, name in ((1, "stdout"), (2, "stderr")):
        if getattr(sys, name) is None:
            try:
                stream = os.fdopen(os.dup(fd), "w", encoding="utf-8")
            except OSError:
                try:
                    stream = open("CONOUT$", "w", encoding="utf-8")
                except OSError:
                    continue
            setattr(sys, name, stream)


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        if any(arg in sys.argv for arg in ("--inspect", "-h", "--help")):
            connect_cli_output()
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        from rhythm_helper.app import main

        result = main()
    except Exception as error:
        if sys.stderr:
            traceback.print_exc()
        if sys.platform == "win32" and "--inspect" not in sys.argv:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"{PRODUCT_NAME} 无法启动。\n\n{error}", PRODUCT_NAME, 0x10
            )
        result = 1
    raise SystemExit(result)
