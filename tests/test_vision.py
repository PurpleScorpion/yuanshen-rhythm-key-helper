"""Synthetic scene tests; no screen capture or key injection is performed."""

import cv2
import numpy as np
import pytest

from rhythm_helper.vision import Detector, Observation


def bgr(hue: int, saturation: int, value: int) -> tuple[int, int, int]:
    hsv = np.uint8([[[hue, saturation, value]]])
    return tuple(int(c) for c in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])


def test_round_heads_with_ribbon_and_star() -> None:
    frame = np.zeros((480, 400, 3), dtype=np.uint8)
    cv2.circle(frame, (120, 250), 41, bgr(20, 185, 242), -1)
    cv2.circle(frame, (120, 250), 13, bgr(20, 130, 250), -1)
    cv2.rectangle(frame, (239, 0), (321, 200), bgr(130, 100, 130), -1)
    cv2.circle(frame, (280, 200), 41, bgr(127, 125, 250), -1)
    cv2.circle(frame, (280, 200), 13, bgr(127, 87, 250), -1)
    found = Detector([120, 280], 420).detect(frame)
    assert [(h.lane, h.kind) for h in found.heads] == [(0, "tap"), (1, "hold")]
    assert found.heads[0].y == pytest.approx(250, abs=1)
    assert found.heads[1].y == pytest.approx(200, abs=1)
    assert found.tail_present == [False, False]


def test_dim_tail_is_not_a_head_and_white_judgement_circle_does_not_hide_it() -> None:
    frame = np.zeros((480, 400, 3), dtype=np.uint8)
    cv2.rectangle(frame, (239, 120), (321, 479), bgr(130, 100, 130), -1)
    cv2.circle(frame, (280, 120), 41, bgr(130, 115, 138), -1)
    cv2.circle(frame, (280, 420), 17, (240, 240, 240), -1)
    found = Detector([120, 280], 420).detect(frame)
    assert found.heads == []
    assert found.tail_present == [False, True]


def test_tail_disappears_as_end_cap_reaches_hit_line() -> None:
    detector = Detector([120], 420)
    states = []
    for y in (340, 390, 420, 460):
        frame = np.zeros((480, 240, 3), dtype=np.uint8)
        cv2.rectangle(frame, (79, y), (161, 479), bgr(130, 100, 130), -1)
        cv2.circle(frame, (120, y), 41, bgr(130, 115, 138), -1)
        states.append(detector.detect(frame).tail_present[0])
    assert states == [True, True, False, False]


def test_background_purple_and_yellow_hit_glow_are_rejected() -> None:
    frame = np.empty((480, 400, 3), dtype=np.uint8)
    frame[:] = bgr(130, 100, 130)
    # Hollow large hit animation is different from an 82px filled note head.
    cv2.circle(frame, (120, 420), 100, bgr(25, 190, 250), 7)
    found = Detector([120, 280], 420).detect(frame)
    assert found.heads == []
    assert found.tail_present == [False, False]
    assert found.hold_support == [0.0, 0.0]


def test_half_size_scene_and_cropped_coordinates() -> None:
    frame = np.zeros((240, 200, 3), dtype=np.uint8)
    cv2.circle(frame, (60, 100), 20, bgr(20, 185, 242), -1)
    found = Detector([60, 140], 210, scale=0.5).detect(frame)
    assert [(h.lane, h.kind) for h in found.heads] == [(0, "tap")]
    assert found.heads[0].y == pytest.approx(100, abs=1)
    cropped = Detector([60, 140], 160, scale=0.5).detect(frame[50:])
    assert cropped.heads[0].y == pytest.approx(50, abs=1)


def test_clipped_or_off_lane_circle_is_not_a_head() -> None:
    frame = np.zeros((480, 400, 3), dtype=np.uint8)
    cv2.circle(frame, (120, 15), 41, bgr(20, 185, 242), -1)
    cv2.circle(frame, (310, 250), 41, bgr(20, 185, 242), -1)
    assert Detector([120, 280], 420).detect(frame).heads == []


def test_invalid_image_is_reported() -> None:
    with pytest.raises(ValueError, match="uint8 BGR"):
        Detector([120], 420).detect(np.zeros((480, 240), dtype=np.uint8))
    with pytest.raises(ValueError, match="positive"):
        Detector([120], 420, scale=0)


@pytest.mark.parametrize("tail_value", [130, 250])
def test_bright_start_and_end_are_distinguished_by_ribbon_direction(tail_value: int) -> None:
    frame = np.zeros((700, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 150), (161, 530), bgr(127, 125, tail_value), -1)
    cv2.circle(frame, (120, 150), 41, bgr(127, 125, 250), -1)
    cv2.circle(frame, (120, 530), 41, bgr(127, 125, 250), -1)
    found = Detector([120], 620).detect(frame)
    assert [(h.kind, round(h.y)) for h in found.heads] == [("end", 150), ("hold", 530)]


def test_crop_without_above_context_is_not_assumed_to_be_end() -> None:
    frame = np.zeros((700, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 0), (161, 530), bgr(127, 125, 130), -1)
    cv2.circle(frame, (120, 70), 41, bgr(127, 125, 250), -1)
    found = Detector([120], 620).detect(frame)
    assert [(h.kind, round(h.y)) for h in found.heads] == [("hold", 70)]


def test_end_remains_identifiable_close_to_capture_bottom() -> None:
    frame = np.zeros((500, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 420), (161, 499), bgr(127, 125, 130), -1)
    cv2.circle(frame, (120, 420), 41, bgr(127, 125, 250), -1)
    found = Detector([120], 420).detect(frame)
    assert [(h.kind, round(h.y)) for h in found.heads] == [("end", 420)]


def test_bright_plain_ribbon_is_not_a_circle() -> None:
    frame = np.zeros((700, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 150), (161, 530), bgr(127, 125, 250), -1)
    assert Detector([120], 620).detect(frame).heads == []


def test_two_field_observation_construction_remains_supported() -> None:
    assert Observation([], [False]).hold_support is None


@pytest.mark.parametrize("glow_radius", [110, 150])
def test_upper_ribbon_support_survives_judgement_glow(glow_radius: int) -> None:
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 80), (161, 579), bgr(127, 125, 130), -1)
    cv2.circle(frame, (120, 500), glow_radius, (250, 250, 250), -1)
    found = Detector([120], 500).detect(frame)
    assert found.tail_present == [False]
    assert found.hold_support == [248.0]


def test_hold_support_needs_adjacent_bands_not_an_isolated_patch() -> None:
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 350), (161, 372), bgr(127, 125, 130), -1)
    assert Detector([120], 500).detect(frame).hold_support == [0.0]
    # Extending the same strip through the next probe gives a distance bound.
    cv2.rectangle(frame, (79, 310), (161, 372), bgr(127, 125, 130), -1)
    assert Detector([120], 500).detect(frame).hold_support == [128.0]


def test_hold_support_rejects_clothing_that_blends_into_either_side() -> None:
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    # The average side contrast is positive, but each patch reaches one side.
    cv2.rectangle(frame, (53, 274), (152, 290), bgr(127, 125, 130), -1)
    cv2.rectangle(frame, (88, 234), (187, 250), bgr(127, 125, 130), -1)
    assert Detector([120], 500).detect(frame).hold_support == [0.0]


def test_hold_support_distance_scales_with_frame_and_preserves_crop_coordinates() -> None:
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 80), (161, 579), bgr(127, 125, 130), -1)
    cv2.circle(frame, (120, 500), 110, (250, 250, 250), -1)
    half = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_NEAREST)
    assert Detector([60], 250, scale=0.5).detect(half).hold_support == [124.0]
    assert Detector([120], 420).detect(frame[80:]).hold_support == [248.0]


def test_missing_upper_capture_context_does_not_invent_hold_support() -> None:
    frame = np.zeros((160, 240, 3), dtype=np.uint8)
    cv2.rectangle(frame, (79, 0), (161, 159), bgr(127, 125, 130), -1)
    assert Detector([120], 90).detect(frame).hold_support == [0.0]


def test_isolated_high_future_ribbon_is_not_support_for_current_hold() -> None:
    frame = np.zeros((580, 240, 3), dtype=np.uint8)
    # Only offsets 250/290 pass. No continuous ribbon reaches the lower probes.
    cv2.rectangle(frame, (79, 190), (161, 255), bgr(127, 125, 130), -1)
    assert Detector([120], 500).detect(frame).hold_support == [0.0]
    # A separate positive 90px probe must not bridge the large empty gap.
    cv2.rectangle(frame, (79, 390), (161, 415), bgr(127, 125, 130), -1)
    assert Detector([120], 500).detect(frame).hold_support == [0.0]
