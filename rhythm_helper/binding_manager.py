"""Keep the registered shortcuts and the saved configuration consistent."""

from .keybinds import DEFAULT_HOTKEYS, validate
from .settings import save_config


class BindingManager:
    def __init__(self, settings, path, factory):
        self.settings = settings
        self.path = path
        self.factory = factory
        self.service = None

    @property
    def bindings(self):
        return self.settings.get("hotkeys", DEFAULT_HOTKEYS)

    def start(self):
        self.service = self.factory(self.bindings)

    def poll(self):
        return self.service.poll() if self.service else []

    def apply(self, requested):
        new = validate(requested)
        old = self.bindings
        previous = self.service
        if previous:
            try:
                previous.rebind(new)
            except RuntimeError:
                # A normal registration conflict leaves the old service alive.
                # A failed rollback or an owner-thread failure requires a fresh one.
                try:
                    previous.poll()
                except RuntimeError:
                    self.close()
                raise
        else:
            self.service = self.factory(new)

        candidate = dict(self.settings, hotkeys=new)
        try:
            save_config(self.path, candidate)
        except (OSError, ValueError) as error:
            if previous:
                try:
                    previous.rebind(old)
                except RuntimeError as rollback_error:
                    self.close()
                    raise RuntimeError(
                        f"配置保存失败，快捷键监听已停止：{rollback_error}"
                    ) from error
            else:
                self.close()
            raise RuntimeError(f"快捷键配置未保存：{error}") from error
        self.settings.update(candidate)
        return new

    def close(self):
        service, self.service = self.service, None
        if service:
            service.close()
