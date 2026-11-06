"""Draw a synthetic six-lane practice frame for the calibration window."""

import cv2
import numpy as np

from .settings import DEFAULTS, geometry


def _draw_note(frame, x, y, fill, highlight):
    cv2.circle(frame, (x, y), 33, (202, 202, 204), -1, cv2.LINE_AA)
    cv2.circle(frame, (x, y), 30, (65, 59, 60), -1, cv2.LINE_AA)
    cv2.circle(frame, (x, y), 27, fill, -1, cv2.LINE_AA)
    star = np.array(
        [(0, -12), (4, -4), (12, 0), (4, 4), (0, 12), (-4, 4), (-12, 0), (-4, -4)],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [star + (x, y)], highlight, cv2.LINE_AA)


def demo_frame() -> np.ndarray:
    """Return a fresh 1280×720 BGR image using the default lane coordinates."""
    width, height = 1280, 720
    lane_x, hit_y, _ = geometry(DEFAULTS, width, height)
    lanes = [round(x) for x in lane_x]
    line_y = round(hit_y)

    gradient = np.linspace((31, 26, 19), (53, 43, 31), height, dtype=np.uint8)
    frame = np.broadcast_to(gradient[:, None, :], (height, width, 3)).copy()
    half_spacing = round((lanes[-1] - lanes[0]) / 10)
    left, right = lanes[0] - half_spacing, lanes[-1] + half_spacing
    for index, x in enumerate(lanes):
        frame[52 : line_y + 26, x - half_spacing : x + half_spacing] += 6 + 3 * (index % 2)
        cv2.line(frame, (x, 52), (x, line_y), (74, 67, 55), 1, cv2.LINE_AA)
    for y in range(120, line_y, 102):
        cv2.line(frame, (left, y), (right, y), (57, 49, 39), 1, cv2.LINE_AA)

    # Coloured notes stay well above the six white targets used for calibration.
    _draw_note(frame, lanes[2], 444, (60, 186, 242), (155, 222, 255))
    purple_x, end_y, start_y = lanes[4], 162, 362
    cv2.rectangle(frame, (purple_x - 26, end_y), (purple_x + 26, start_y), (120, 71, 88), -1)
    for edge in (purple_x - 27, purple_x + 27):
        cv2.line(frame, (edge, end_y), (edge, start_y), (160, 116, 135), 2, cv2.LINE_AA)
    for y in (end_y, start_y):
        _draw_note(frame, purple_x, y, (247, 132, 155), (253, 188, 212))

    cv2.line(frame, (left, line_y), (right, line_y), (176, 173, 162), 2, cv2.LINE_AA)
    for x, key in zip(lanes, DEFAULTS["keys"], strict=True):
        cv2.circle(frame, (x, line_y), 17, (120, 118, 105), 1, cv2.LINE_AA)
        cv2.circle(frame, (x, line_y), 11, (255, 255, 255), -1, cv2.LINE_AA)
        label = key.upper()
        font = cv2.FONT_HERSHEY_SIMPLEX
        (text_width, _), _ = cv2.getTextSize(label, font, 0.78, 2)
        cv2.putText(
            frame,
            label,
            (x - text_width // 2, line_y + 48),
            font,
            0.78,
            (218, 217, 211),
            2,
            cv2.LINE_AA,
        )
    return frame
