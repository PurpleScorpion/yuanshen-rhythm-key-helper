"""Bridge between Tk's UI thread and the capture/input worker."""

from __future__ import annotations

from collections import deque
from threading import Event, Lock, Thread


class GuiSession:
    def __init__(self, settings, path, *, dry_run=False):
        self.settings, self.path, self.dry_run = settings, path, dry_run
        self.parent = None
        self._lock = Lock()
        self._commands = deque()
        self._events = deque(maxlen=800)
        self._closing = Event()
        self._disarmed = False
        self._editing_hotkeys = False
        self._thread = Thread(target=self._run, name="rhythm-capture", daemon=False)

    def start(self):
        self._thread.start()

    @property
    def alive(self):
        return self._thread.is_alive()

    @property
    def closing(self):
        return self._closing.is_set()

    def publish(self, kind, payload):
        with self._lock:
            self._events.append((kind, payload))

    def drain(self):
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def command(self, name):
        if name not in ("start", "stop", "calibrate", "tutorial"):
            raise ValueError(f"未知界面操作：{name}")
        with self._lock:
            if not self.closing:
                self._disarmed |= name != "start"
                self._commands.append(name)

    def poll(self):
        with self._lock:
            commands = list(self._commands)
            self._commands.clear()
            self._disarmed = False
        return commands

    def begin_hotkey_edit(self):
        with self._lock:
            if not self.closing:
                self._editing_hotkeys = True
                self._disarmed = True
                self._commands.append("edit_begin")

    def end_hotkey_edit(self):
        with self._lock:
            self._editing_hotkeys = False
            self._commands.append("edit_end")

    def set_hotkeys(self, mapping):
        with self._lock:
            if not self.closing:
                self._disarmed = True
                self._commands.append(("hotkeys", dict(mapping)))

    def route(self, physical, bindings):
        """Registered combinations arrive via WM_HOTKEY, not Tk KeyPress."""
        with self._lock:
            queued = list(self._commands)
            self._commands.clear()
            self._disarmed = False
            editing = self._editing_hotkeys
            transitioning = any(c in ("edit_begin", "edit_end") for c in queued)
            if editing or transitioning:
                if editing:
                    for action in physical:
                        if action in bindings:
                            self._events.append(("hotkey_capture", bindings[action]))
                # Preserve a fresh button click made just after the editor closed.
                routed = []
                gate = True
                for command in queued:
                    if command in ("edit_begin", "edit_end"):
                        gate = command == "edit_begin"
                        routed.append(command)
                    elif not gate or command == "stop" or isinstance(command, tuple):
                        routed.append(command)
                return routed
        return physical + queued

    def close(self):
        with self._lock:
            self._closing.set()
            self._commands.clear()

    def press(self, output, key):
        with self._lock:
            if self.closing or self._disarmed or self._editing_hotkeys:
                return False
            output.press(key)
            return True

    def _run(self):
        from .app import runtime

        error = None
        try:
            runtime(self.settings, self.path, dry_run=self.dry_run, gui=self)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        finally:
            self.publish("exit", error)

    def open_picker(self, draw, hotkeys):
        """Keep the worker as sole consumer of hotkeys while Tk shows the picker."""
        finished, entered, dismissed = Event(), Event(), Event()
        modal_lock = Lock()
        pending = deque(maxlen=32)
        errors = []
        result = False
        session = self

        class PickerControls:
            def poll(self):
                if session.closing:
                    return ["stop"]
                with modal_lock:
                    commands = list(pending)
                    pending.clear()
                return commands

        def show():
            nonlocal result
            with modal_lock:
                if dismissed.is_set():
                    return
                entered.set()
            try:
                if not self.closing:
                    result = draw(PickerControls(), self.parent)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        self.publish("calibration", show)
        while not finished.wait(0.015):
            # A settings click can race a calibration already posted to Tk.
            # Leave editor commands queued for the worker's normal command loop.
            with self._lock:
                editing = self._editing_hotkeys or any(
                    isinstance(cmd, tuple) or cmd in ("edit_begin", "edit_end")
                    for cmd in self._commands
                )
                if not editing:
                    ui_commands = list(self._commands)
                    self._commands.clear()
                    self._disarmed = False
            if self.closing or editing:
                with modal_lock:
                    if not entered.is_set():
                        dismissed.set()
                        return False
                    pending.append("stop")
                continue
            try:
                commands = hotkeys.poll() + ui_commands
            except RuntimeError as exc:
                if not errors:
                    errors.append(exc)
                commands = ["stop"]
            with modal_lock:
                pending.extend(commands)
        if errors:
            raise RuntimeError(str(errors[0])) from errors[0]
        return result
