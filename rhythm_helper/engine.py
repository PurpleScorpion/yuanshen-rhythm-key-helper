"""Pure tracking/state machine; no screen access or keyboard side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from .vision import Head, Observation


@dataclass(frozen=True)
class Action:
    key: str
    down: bool
    reason: str


@dataclass
class Track:
    identity: int
    lane: int
    kind: str
    y: float
    seen: float
    motion_y: float
    motion_at: float
    speed: float = 0.0
    samples: int = 1
    motion_samples: int = 0
    travel: float = 0.0
    fired: bool = False
    end_votes: int = 0
    last_end_y: float | None = None
    confirmed_end: bool = False
    endpoint_at: float | None = None
    endpoint_estimates: list[float] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)

    def predicted_y(self, now: float) -> float:
        return self.motion_y + self.speed * max(0, now - self.motion_at)

    def arrival(self, hit_y: float, lead: float) -> float:
        return self.motion_at + (hit_y - self.motion_y) / self.speed - lead

    def moving(self, scale: float) -> bool:
        return self.samples >= 2 and self.travel >= 12 * scale and self.speed >= 80 * scale

    def observe_role(self, kind: str, y: float, scale: float) -> None:
        # A fired start is still the same circle when judgement effects change
        # its apparent ribbon direction. It can never become its own endpoint.
        if self.fired or self.confirmed_end or self.kind == "tap":
            return
        self.kind = kind
        if kind == "end":
            # Repeated captures of one game frame are not independent evidence.
            if self.last_end_y is None or y - self.last_end_y >= 2 * scale:
                self.end_votes += 1
                self.last_end_y = y
            if self.end_votes >= 3:
                self.confirmed_end = True
        else:
            self.end_votes = 0
            self.last_end_y = None


@dataclass
class Pressed:
    kind: str
    since: float
    start_track_id: int
    start_at: float
    speed: float
    absent_since: float | None = None
    tail_seen: bool = False
    not_before: float = 0.0
    end_track_id: int | None = None
    end_at: float | None = None
    support_seen: bool = False


class Engine:
    def __init__(
        self,
        hit_y: float,
        *,
        scale: float = 1,
        keys: tuple[str, ...] = ("a", "s", "d", "j", "k", "l"),
        lead_ms: float = 8,
        tap_ms: float = 28,
        release_grace_ms: float = 65,
        max_hold_seconds: float = 30,
        allow_color_release: bool = False,
    ) -> None:
        self.hit_y, self.scale, self.keys = hit_y, scale, keys
        self.lead = lead_ms / 1000
        self.tap_duration = tap_ms / 1000
        self.release_grace = release_grace_ms / 1000
        self.max_hold = max_hold_seconds
        self.allow_color_release = allow_color_release
        self.tracks: list[Track] = []
        self.pressed: dict[int, Pressed] = {}
        self._next_identity = 0

    def stop(self) -> list[Action]:
        actions = [Action(self.keys[lane], False, "stop") for lane in self.pressed]
        self.pressed.clear()
        self.tracks.clear()
        return actions

    def _keep_track(self, track: Track, now: float) -> bool:
        if now - track.seen <= 0.18:
            return True
        # A confirmed moving endpoint remains useful behind judgement effects.
        # Preserve its ETA, including when it was seen before key-down.
        return (
            track.endpoint_at is not None
            and not track.fired
            and now - track.seen <= self.max_hold
            and now <= track.endpoint_at + 0.18
        )

    def _update_tracks(self, heads: list[Head], now: float) -> None:
        self.tracks = [track for track in self.tracks if self._keep_track(track, now)]
        pairs = []
        for index, head in enumerate(heads):
            for track_index, track in enumerate(self.tracks):
                same_family = (head.kind == "tap") == (track.kind == "tap")
                if head.lane != track.lane or not same_family:
                    continue
                if head.y < track.y - 8 * self.scale:
                    continue
                dt = max(0, now - track.motion_at)
                if track.motion_samples:
                    # Bound the prediction error below adjacent circle spacing.
                    gate = min(60 * self.scale, max(36 * self.scale, track.speed * dt * 0.5))
                else:
                    gate = max(36 * self.scale, min(0.12, dt) * 3000 * self.scale)
                # A screenshot can repeat the previous game frame. Match both
                # that position and the prediction from the last actual move.
                distance = min(abs(head.y - track.y), abs(head.y - track.predicted_y(now)))
                if distance <= gate:
                    pairs.append((distance, index, track_index))
        used_heads: set[int] = set()
        used_tracks: set[int] = set()
        for _, index, track_index in sorted(pairs):
            if index in used_heads or track_index in used_tracks:
                continue
            track, head = self.tracks[track_index], heads[index]
            dt = now - track.motion_at
            delta = head.y - track.motion_y
            moved = dt > 0 and delta >= 2 * self.scale
            if moved:
                measured_speed = min(3000 * self.scale, delta / dt)
                track.positions.append((now, head.y))
                track.positions = [(t, y) for t, y in track.positions if now - t <= 0.14]
                # Use motion across several game frames. Adjacent screenshots
                # have irregular spacing and pixel-level centroid noise.
                slopes = [
                    (y2 - y1) / (t2 - t1)
                    for i, (t1, y1) in enumerate(track.positions)
                    for t2, y2 in track.positions[i + 1 :]
                    if t2 - t1 >= 0.045
                ]
                if slopes:
                    measured_speed = max(0, min(3000 * self.scale, median(slopes)))
                track.speed = (
                    measured_speed
                    if not track.motion_samples
                    else measured_speed
                    if slopes
                    else 0.5 * track.speed + 0.5 * measured_speed
                )
                track.motion_samples += 1
                track.motion_y, track.motion_at = head.y, now
            track.travel += max(0, head.y - track.y)
            track.observe_role(head.kind, head.y, self.scale)
            track.y, track.seen = head.y, now
            track.samples += 1
            if (
                moved
                and not track.fired
                and track.confirmed_end
                and head.kind == "end"
                and track.moving(self.scale)
            ):
                # A confirmed end can later look like a start when its lower
                # ribbon/circle is hidden by hit effects. Those partial shapes
                # retain identity but must not turn a biased centroid into a
                # fictitious slowdown. Use only still-supported end geometry.
                track.endpoint_estimates.append(track.arrival(self.hit_y, self.lead))
                del track.endpoint_estimates[:-5]
                track.endpoint_at = median(track.endpoint_estimates)
            used_heads.add(index)
            used_tracks.add(track_index)

        for index, head in enumerate(heads):
            if index in used_heads or head.y > self.hit_y - 65 * self.scale:
                continue
            if head.kind not in ("tap", "hold", "end"):
                continue
            self._next_identity += 1
            track = Track(self._next_identity, head.lane, head.kind, head.y, now, head.y, now)
            track.positions.append((now, head.y))
            track.observe_role(head.kind, head.y, self.scale)
            self.tracks.append(track)

    def _bind_endpoint(self, lane: int, state: Pressed) -> None:
        next_start = min(
            (
                track.arrival(self.hit_y, self.lead)
                for track in self.tracks
                if track.lane == lane
                and track.identity != state.start_track_id
                and not track.fired
                and track.kind == "hold"
                and not track.confirmed_end
                and track.moving(self.scale)
                and track.arrival(self.hit_y, self.lead) > state.start_at + 0.005
            ),
            default=float("inf"),
        )
        if state.end_at is not None and state.end_at >= next_start:
            state.end_track_id, state.end_at = None, None
        candidates = []
        for track in self.tracks:
            if (
                track.lane != lane
                or track.identity == state.start_track_id
                or track.fired
                or not track.confirmed_end
                or track.endpoint_at is None
            ):
                continue
            arrival = track.endpoint_at
            if (
                state.start_at + 0.005 < arrival < next_start
                and arrival <= state.since + self.max_hold
            ):
                candidates.append((arrival, track))
        if not candidates:
            return  # A saved ETA survives pruning or a hidden endpoint.
        arrival, endpoint = min(candidates, key=lambda item: item[0])
        if (
            state.end_track_id is None
            or state.end_track_id == endpoint.identity
            or state.end_at is None
            or arrival < state.end_at
        ):
            state.end_track_id, state.end_at = endpoint.identity, arrival
            state.speed = endpoint.speed

    def _observe_ribbon(
        self, lane: int, state: Pressed, observation: Observation, now: float
    ) -> None:
        supports = getattr(observation, "hold_support", None)
        distance = max(0.0, supports[lane]) if supports is not None else 0.0
        if distance > 0:
            upper_sample_y = self.hit_y - distance - 42 * self.scale
            if any(
                track.lane == lane
                and track.identity != state.start_track_id
                and not track.fired
                and track.kind == "hold"
                and upper_sample_y < track.predicted_y(now) < self.hit_y
                for track in self.tracks
            ):
                # The ribbon above a separate upcoming start belongs to that
                # next note; it must not prolong the currently held note.
                distance = 0.0
        present = observation.tail_present[lane] or distance > 0
        if present:
            state.tail_seen = True
            state.absent_since = None
        elif state.absent_since is None:
            state.absent_since = now
        if distance > 0 and state.speed > 0:
            state.support_seen = True
            # Allow 25% velocity uncertainty to make this a conservative lower
            # bound. A trusted cap ETA takes priority over this auxiliary hint.
            state.not_before = max(state.not_before, now + distance / (state.speed * 1.25))

    def _release_reason(self, state: Pressed, now: float) -> str:
        if state.kind == "tap":
            return "tap complete" if now - state.since >= self.tap_duration else ""
        if now - state.since >= self.max_hold:
            return "hold timeout"
        if state.end_at is not None:
            return "end cap" if now >= state.end_at else ""
        if (
            self.allow_color_release
            and state.tail_seen
            and state.absent_since is not None
            and now - state.since >= 0.12
            and now - state.absent_since
            >= max(self.release_grace, 0.18 if state.support_seen else 0.0)
            and now >= state.not_before
        ):
            return "tail ended"
        return ""

    def _release_due(self, now: float, actions: list[Action]) -> None:
        for lane, state in list(self.pressed.items()):
            reason = self._release_reason(state, now)
            if not reason:
                continue
            actions.append(Action(self.keys[lane], False, reason))
            if state.end_track_id is not None:
                for track in self.tracks:
                    if track.identity == state.end_track_id:
                        track.fired = True
            del self.pressed[lane]

    def step(
        self, observation: Observation, now: float, *, action_at: float | None = None
    ) -> list[Action]:
        actions: list[Action] = []
        # Incorporate endpoint measurements before deciding whether to release.
        self._update_tracks(observation.heads, now)
        # Coordinates belong to capture time; decisions happen after detection.
        # Account for that elapsed work instead of adding it to every hit.
        now = max(now, action_at) if action_at is not None else now
        for lane, state in self.pressed.items():
            if state.kind == "hold":
                self._bind_endpoint(lane, state)
                self._observe_ribbon(lane, state, observation, now)
        self._release_due(now, actions)

        for track in sorted(self.tracks, key=lambda item: item.y, reverse=True):
            if track.fired or not track.moving(self.scale):
                continue
            if track.kind == "end":
                # Endpoints only release independently started holds via their
                # saved deadlines. An orphan end can never synthesize key-down.
                continue
            if now - track.seen > 0.14:
                continue
            y = track.predicted_y(now) + track.speed * self.lead
            if y < self.hit_y:
                continue
            track.fired = True
            if y > self.hit_y + 55 * self.scale:
                continue
            old = self.pressed.get(track.lane)
            if old and old.kind == "hold":
                # An independent new note at the line proves the preceding
                # hold has finished, even if its endpoint was never visible.
                actions.append(Action(self.keys[track.lane], False, "next note (unseen end)"))
                old = None
            if old:
                actions.append(Action(self.keys[track.lane], False, "next note"))
            state = Pressed(
                kind=track.kind,
                since=now,
                start_track_id=track.identity,
                start_at=track.arrival(self.hit_y, self.lead),
                speed=track.speed,
            )
            self.pressed[track.lane] = state
            actions.append(Action(self.keys[track.lane], True, track.kind))
            if track.kind == "hold":
                self._bind_endpoint(track.lane, state)
                self._observe_ribbon(track.lane, state, observation, now)
        # At low FPS a genuinely short hold may cross both endpoints in a frame.
        # Only a separate confirmed cap can release a new hold here.
        self._release_due(now, actions)
        for track in self.tracks:
            if track.endpoint_at is not None and now >= track.endpoint_at:
                track.fired = True
        return actions
