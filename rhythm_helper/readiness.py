"""Require a stable, foreground client area before arming screen recognition."""

from dataclasses import dataclass


@dataclass
class WindowReadiness:
    stable_seconds: float = 0.30
    signature: tuple[int, tuple[int, int, int, int]] | None = None
    since: float = 0.0

    def reset(self) -> None:
        self.signature = None

    def observe(self, hwnd: int, rect: tuple[int, int, int, int] | None, now: float) -> bool:
        if rect is None or rect[2] < 640 or rect[3] < 360:
            self.reset()
            return False
        signature = (hwnd, rect)
        if signature != self.signature:
            self.signature, self.since = signature, now
            return False
        return now - self.since >= self.stable_seconds
