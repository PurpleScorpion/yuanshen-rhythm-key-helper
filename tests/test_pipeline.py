"""Real vision-to-engine sequences; no screen access or native key injection.

Frames contain an actual coloured ribbon and circular start/end caps. A large
judgement flash hides the lower ribbon after the start reaches the hit line,
then hides the end cap for substantially longer than the old prediction TTL.
"""

import cv2
import numpy as np
import pytest

from rhythm_helper.engine import Engine
from rhythm_helper.vision import Detector

HIT_Y = 500
LANE_X = 120
SPEED = 500.0
START_AT = 0.5
END_AT = 1.7
GLOW_RADIUS = 110


def _bgr(hue: int, saturation: int, value: int) -> tuple[int, int, int]:
    hsv = np.uint8([[[hue, saturation, value]]])
    return tuple(int(channel) for channel in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])


def _hold_frame(display_time: float) -> np.ndarray:
    """Draw the same long note moving down at a known physical speed."""
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    start_y = round(HIT_Y + (display_time - START_AT) * SPEED)
    end_y = round(HIT_Y + (display_time - END_AT) * SPEED)
    ribbon = _bgr(127, 125, 130)
    circle = _bgr(127, 125, 250)
    cv2.rectangle(frame, (LANE_X - 41, end_y), (LANE_X + 41, start_y), ribbon, -1)
    cv2.circle(frame, (LANE_X, start_y), 41, circle, -1)
    cv2.circle(frame, (LANE_X, end_y), 41, circle, -1)
    if display_time >= START_AT:
        cv2.circle(frame, (LANE_X, HIT_Y), GLOW_RADIUS, (250, 250, 250), -1)
    return frame


@pytest.mark.parametrize(
    ("capture_fps", "game_fps"),
    [(120, 120), (120, 60), (60, 30)],
    ids=["120fps", "120hz-capture-60fps-game", "60hz-capture-30fps-game"],
)
def test_long_hold_survives_flash_and_releases_at_hidden_end(capture_fps, game_fps):
    detector = Detector([LANE_X], HIT_Y)
    engine = Engine(HIT_Y, keys=("k",), lead_ms=0)
    events = []
    last_display_frame = -1
    frame = None
    repeated_frames = 0
    supported_occluded_frames = 0
    end_observations = []

    for tick in range(round((END_AT + 0.4) * capture_fps) + 1):
        now = tick / capture_fps
        # Integer arithmetic makes repeated screenshots deterministic; the
        # detector and engine still run on every capture, including duplicates.
        display_frame = tick * game_fps // capture_fps
        if display_frame != last_display_frame:
            frame = _hold_frame(display_frame / game_fps)
            last_display_frame = display_frame
        else:
            repeated_frames += 1
        assert frame is not None
        observation = detector.detect(frame)
        assert observation.hold_support is not None
        if any(head.kind == "end" for head in observation.heads):
            end_observations.append(now)
        if (
            START_AT + 0.1 <= now <= END_AT - 0.5
            and not observation.tail_present[0]
            and observation.hold_support[0] > 0
        ):
            supported_occluded_frames += 1
        events.extend((now, action) for action in engine.step(observation, now))

        # A flash after a correct start must not reduce a long hold to a tap.
        if START_AT + 0.1 <= now <= END_AT - 0.1:
            assert 0 in engine.pressed, f"Hold released early at t={now:.3f}s; {events=}"

    assert supported_occluded_frames >= game_fps // 2
    assert len(end_observations) >= 4
    assert END_AT - max(end_observations) > 0.20
    assert [(action.key, action.down) for _, action in events] == [("k", True), ("k", False)]
    assert events[0][1].reason == "hold"
    assert events[1][1].reason == "end cap"
    tolerance = max(0.04, 2 / game_fps)
    assert events[0][0] == pytest.approx(START_AT, abs=tolerance)
    assert events[1][0] == pytest.approx(END_AT, abs=tolerance)
    assert events[1][0] - events[0][0] == pytest.approx(END_AT - START_AT, abs=tolerance)
    assert not engine.pressed
    assert engine.stop() == []
    if capture_fps > game_fps:
        assert repeated_frames >= game_fps
