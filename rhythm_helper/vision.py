"""Colour/shape recognition for the six-lane UI in the supplied screenshots.

All coordinates are relative to the supplied BGR frame. The detector does not
press keys: a moving-note tracker must decide when a head reaches the hit line.
"""

import math
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class Head:
    lane: int
    kind: Literal["tap", "hold", "end"]
    y: float


@dataclass(frozen=True, slots=True)
class Observation:
    heads: list[Head]
    tail_present: list[bool]
    # Lower bound on pixels still to travel, supported by an upper ribbon.
    # This is positive hold evidence, never proof that the note has ended.
    # None preserves callers that construct the original two-field observation.
    hold_support: list[float] | None = None


class Detector:
    """Recognize coloured circular heads and the active purple ribbon.

    ``scale=1`` corresponds to the supplied 1920x1080 screenshots. HSV hue uses
    OpenCV's 0..179 range. Thresholds are deliberately narrower for heads than
    for translucent tails. The latter are compared with neighbouring background
    pixels so purple clothing/shadows do not automatically hold a key forever.
    """

    HEAD_RANGES = {
        "tap": ((15, 110, 170), (38, 255, 255)),
        "hold": ((118, 80, 185), (151, 255, 255)),
    }
    TAIL_RANGE = ((118, 45, 65), (151, 255, 255))
    TAIL_OFFSET = 41.0
    SUPPORT_OFFSETS = (90, 130, 170, 210, 250, 290)

    def __init__(self, lane_x: list[float], hit_y: float, scale: float = 1.0) -> None:
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("scale must be a positive finite number")
        if not lane_x or not all(math.isfinite(x) for x in lane_x):
            raise ValueError("lane_x must contain finite coordinates")
        if not math.isfinite(hit_y):
            raise ValueError("hit_y must be finite")
        self.lane_x = list(lane_x)
        self.hit_y = hit_y
        self.scale = scale

    def detect(self, frame: np.ndarray) -> Observation:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("frame must be an H x W x 3 uint8 BGR image")
        if not frame.size:
            raise ValueError("frame must not be empty")
        heads: list[Head] = []
        tails: list[bool] = []
        support: list[float] = []
        height, width = frame.shape[:2]
        half_width = max(2, round(67 * self.scale))
        kernel_size = max(1, round(3 * self.scale))
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        # Only process narrow lane strips; the large gaps contain scenery.
        # This also avoids unnecessary full-width HSV/morphology work per frame.
        for lane, lane_center in enumerate(self.lane_x):
            left = max(0, round(lane_center) - half_width)
            right = min(width, round(lane_center) + half_width + 1)
            if left >= right:
                tails.append(False)
                support.append(0.0)
                continue
            hsv = cv2.cvtColor(frame[:, left:right], cv2.COLOR_BGR2HSV)
            tail_mask = cv2.inRange(hsv, *self.TAIL_RANGE)
            tails.append(self._tail_at(tail_mask, lane_center - left))
            support.append(self._hold_support_at(tail_mask, lane_center - left))
            for kind, (lower, upper) in self.HEAD_RANGES.items():
                mask = cv2.inRange(hsv, lower, upper)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    x, y, w, h = cv2.boundingRect(contour)
                    if not (53 * self.scale <= w <= 113 * self.scale):
                        continue
                    if kind == "hold" and h > 113 * self.scale:
                        # A very bright ribbon can join both circles in the
                        # head mask. Recover only genuinely rounded end caps;
                        # a plain coloured rectangle has no rounded cap.
                        center_x = left + x + (w - 1) / 2
                        if abs(center_x - lane_center) <= 21 * self.scale:
                            for center_y in self._rounded_caps(mask, (x, y, w, h)):
                                if center_y <= self.hit_y + 42 * self.scale:
                                    cap_kind = self._purple_kind(
                                        tail_mask, lane_center - left, center_y
                                    )
                                    heads.append(Head(lane, cap_kind, center_y))
                        continue
                    if not (53 * self.scale <= h <= 113 * self.scale):
                        continue
                    # Clipped heads do not provide a trustworthy centre.
                    if y == 0 or y + h >= height or x == 0 or x + w >= right - left:
                        continue
                    if not 0.72 <= w / h <= 1.38:
                        continue
                    area = cv2.contourArea(contour)
                    perimeter = cv2.arcLength(contour, True)
                    if perimeter <= 0 or area / (w * h) < 0.60:
                        continue
                    if 4 * math.pi * area / (perimeter * perimeter) < 0.66:
                        continue
                    moments = cv2.moments(contour)
                    if moments["m00"] <= 0:
                        continue
                    center_x = left + moments["m10"] / moments["m00"]
                    center_y = moments["m01"] / moments["m00"]
                    if abs(center_x - lane_center) > 21 * self.scale:
                        continue
                    if center_y > self.hit_y + 42 * self.scale:
                        continue
                    head_kind = (
                        self._purple_kind(tail_mask, lane_center - left, center_y)
                        if kind == "hold"
                        else "tap"
                    )
                    heads.append(Head(lane, head_kind, center_y))
        heads.sort(key=lambda head: (head.lane, head.y))
        return Observation(heads, tails, support)

    def _hold_support_at(self, mask: np.ndarray, center_x: float) -> float:
        """Find sustained purple ribbon above the judgement-point glow.

        A probe occupies the 16 reference pixels *above* its offset, making
        ``offset - radius`` a conservative distance bound even if only part of
        its height is purple. Two adjacent probes must pass independently.
        Compare each side separately: clothes can cover a lane and one side,
        while a narrow ribbon has visible contrast against both sides.
        """

        def coverage(start: float, end: float, top: int, bottom: int) -> float | None:
            left = round(center_x + start * self.scale)
            right = round(center_x + end * self.scale) + 1
            if left < 0 or right > mask.shape[1] or left >= right:
                return None
            return float(np.count_nonzero(mask[top:bottom, left:right])) / (
                (bottom - top) * (right - left)
            )

        previous_present = False
        run_start: int | None = None
        remaining = 0.0
        for offset in self.SUPPORT_OFFSETS:
            bottom = round(self.hit_y - offset * self.scale)
            top = bottom - max(1, round(16 * self.scale))
            present = False
            if top >= 0 and bottom <= mask.shape[0]:
                inside = coverage(-32, 32, top, bottom)
                left_side = coverage(-65, -50, top, bottom)
                right_side = coverage(50, 65, top, bottom)
                if inside is not None and left_side is not None and right_side is not None:
                    present = inside >= 0.64 and inside - max(left_side, right_side) >= 0.20
            if not present:
                run_start = None
            elif not previous_present:
                run_start = offset
            # An isolated future note high above the hit point is not support
            # for the current hold. The continuous run must reach the lower
            # visible area, allowing its first 130px to be hidden by a glow.
            if present and previous_present and run_start is not None and run_start <= 170:
                remaining = max(remaining, (offset - 42) * self.scale)
            previous_present = present
        return remaining

    @staticmethod
    def _rounded_caps(mask: np.ndarray, bounds: tuple[int, int, int, int]) -> list[float]:
        x, y, width, height = bounds
        radius = (width - 1) / 2
        candidates = []
        for edge, direction in ((y, 1), (y + height - 1, -1)):
            if edge <= 0 or edge >= mask.shape[0] - 1:
                continue
            near_edge = round(edge + direction * radius * 0.18)
            center = edge + direction * radius
            center_row = round(center)
            edge_fill = np.count_nonzero(mask[near_edge, x : x + width]) / width
            center_fill = np.count_nonzero(mask[center_row, x : x + width]) / width
            if 0.25 <= edge_fill <= 0.78 and center_fill >= 0.80:
                candidates.append(center)
        return candidates

    def _purple_kind(
        self, mask: np.ndarray, center_x: float, center_y: float
    ) -> Literal["hold", "end"]:
        # A hold START has a ribbon above its circle; its END has a ribbon
        # below. Brightness alone cannot distinguish these two circles.
        above_start = round(center_y - 95 * self.scale)
        above_stop = round(center_y - 55 * self.scale)
        if above_start < 0:
            # Missing context at the capture boundary is not evidence of an end.
            return "hold"
        below_start = round(center_y + 55 * self.scale)
        below_stop = min(mask.shape[0], round(center_y + 95 * self.scale))
        if below_stop - below_start < max(3, round(10 * self.scale)):
            return "hold"

        def ribbon(y0: int, y1: int) -> tuple[float, float]:
            def coverage(x0: float, x1: float) -> float:
                left = max(0, round(center_x + x0 * self.scale))
                right = min(mask.shape[1], round(center_x + x1 * self.scale) + 1)
                patch = mask[y0:y1, left:right]
                return float(np.count_nonzero(patch) / patch.size) if patch.size else 0.0

            inside = coverage(-32, 32)
            outside = (coverage(-65, -50) + coverage(50, 65)) / 2
            return inside, inside - outside

        above, _ = ribbon(above_start, above_stop)
        below, contrast = ribbon(below_start, below_stop)
        if above <= 0.30 and below >= 0.45 and contrast >= 0.20:
            return "end"
        return "hold"

    def _tail_at(self, mask: np.ndarray, center_x: float) -> bool:
        # The stationary white judgement circle hides the ribbon at hit_y.
        # An end-cap radius is about 42px: its upper edge leaves this band close
        # to the instant the cap's centre crosses hit_y.
        center_y = self.hit_y - self.TAIL_OFFSET * self.scale
        y0 = max(0, round(center_y - 4 * self.scale))
        y1 = min(mask.shape[0], round(center_y + 4 * self.scale) + 1)
        if y1 <= y0:
            return False

        def coverage(start: float, end: float) -> float:
            left = max(0, round(center_x + start * self.scale))
            right = min(mask.shape[1], round(center_x + end * self.scale) + 1)
            if right <= left:
                return 0.0
            return float(np.count_nonzero(mask[y0:y1, left:right])) / ((y1 - y0) * (right - left))

        inside = coverage(-32, 32)
        background = (coverage(-65, -50) + coverage(50, 65)) / 2
        return inside >= 0.64 and inside - background >= 0.20
