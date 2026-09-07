"""Bounded mouth tracking and motion-aware stride interpolation."""

from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from server.avatar_compositing.compositor import MouthGeometry


def track_mouth_geometry(faces: list[np.ndarray], base: MouthGeometry) -> list[MouthGeometry]:
    """Track source texture against a fixed reference, avoiding accumulated drift.

    This moves the mask with the prepared motion base. It does not infer lip
    opening or smooth speech predictions. Low-confidence frames use the base.
    """
    reference = cv2.cvtColor(faces[0], cv2.COLOR_BGR2GRAY)
    height, width = reference.shape
    mask = np.zeros_like(reference)
    x1, x2 = round((base.center_x - base.rx) * width), round((base.center_x + base.rx) * width)
    y1, y2 = round((base.center_y - .09) * height), round((base.center_y + .09) * height)
    mask[max(0, y1):min(height, y2), max(0, x1):min(width, x2)] = 255
    points = cv2.goodFeaturesToTrack(reference, 32, .015, 4, mask=mask)
    if points is None or len(points) < 5:
        return [base] * len(faces)
    shifts = []
    for face in faces:
        gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
        moved, status, _ = cv2.calcOpticalFlowPyrLK(reference, gray, points, None, winSize=(15, 15), maxLevel=2)
        if moved is None or status is None:
            shifts.append(np.zeros(2))
            continue
        back, reverse_status, _ = cv2.calcOpticalFlowPyrLK(gray, reference, moved, None, winSize=(15, 15), maxLevel=2)
        if back is None or reverse_status is None:
            shifts.append(np.zeros(2))
            continue
        valid = ((status.ravel() == 1) & (reverse_status.ravel() == 1)
                 & (np.linalg.norm((back - points)[:, 0], axis=1) < 1.5))
        shift = np.median((moved - points)[valid, 0], axis=0) if valid.sum() >= 5 else np.zeros(2)
        shifts.append(np.clip(shift / [width, height], -.06, .06))
    shifts_array = np.asarray(shifts)
    # Offline smoothing only affects mask location, never phoneme motion.
    smooth = [np.median(shifts_array[max(0, i - 2):i + 3], axis=0) for i in range(len(faces))]
    return [replace(base, center_x=round((base.center_x + float(dx)) * width) / width,
                    center_y=round((base.center_y + float(dy)) * height) / height)
            for dx, dy in smooth]


def interpolate_mouth(left: np.ndarray, right: np.ndarray, geometry: MouthGeometry) -> np.ndarray:
    """Warp both predicted mouth contours halfway before mixing their texture.

    Bidirectional consistency rejects occluded/unmatched motion. Flow is bounded
    and computed only on a small mouth crop; the rest stays a linear midpoint.
    """
    middle = cv2.addWeighted(left, .5, right, .5, 0)
    height, width = left.shape[:2]
    x1 = max(0, round((geometry.center_x - geometry.rx) * width))
    x2 = min(width, round((geometry.center_x + geometry.rx) * width))
    y1 = max(0, round((geometry.center_y - geometry.ry * 2) * height))
    y2 = min(height, round((geometry.center_y + geometry.ry * geometry.ry_open_factor) * height))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return middle
    size = (min(64, x2 - x1), max(8, round((y2 - y1) * min(64, x2 - x1) / (x2 - x1))))
    first = cv2.resize(left[y1:y2, x1:x2], size)
    second = cv2.resize(right[y1:y2, x1:x2], size)
    first_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    second_gray = cv2.cvtColor(second, cv2.COLOR_BGR2GRAY)
    forward = cv2.calcOpticalFlowFarneback(first_gray, second_gray, None, .5, 2, 11, 3, 5, 1.1, 0)
    backward = cv2.calcOpticalFlowFarneback(second_gray, first_gray, None, .5, 2, 11, 3, 5, 1.1, 0)
    yy, xx = np.mgrid[:size[1], :size[0]].astype(np.float32)
    reverse_at_destination = cv2.remap(backward, xx + forward[:, :, 0], yy + forward[:, :, 1], cv2.INTER_LINEAR)
    confidence = (np.linalg.norm(forward + reverse_at_destination, axis=2) < 1.5).astype(np.float32)
    cap = min(size) * .12
    forward, backward = np.clip(forward, -cap, cap), np.clip(backward, -cap, cap)
    first = cv2.remap(first, xx + backward[:, :, 0] * .5, yy + backward[:, :, 1] * .5,
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    second = cv2.remap(second, xx + forward[:, :, 0] * .5, yy + forward[:, :, 1] * .5,
                       cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    warped = cv2.resize(cv2.addWeighted(first, .5, second, .5, 0), (x2 - x1, y2 - y1))
    # Fade only the interpolation correction at its crop edge. The final source
    # versus prediction composition still has exactly one spatial feather.
    edge_x = np.minimum(np.arange(x2 - x1), np.arange(x2 - x1)[::-1]) / 5
    edge_y = np.minimum(np.arange(y2 - y1), np.arange(y2 - y1)[::-1]) / 5
    confidence = cv2.resize(confidence, (x2 - x1, y2 - y1))
    weight = (confidence * np.clip(edge_y[:, None], 0, 1) * np.clip(edge_x[None, :], 0, 1)).astype(np.float32)
    middle[y1:y2, x1:x2] = cv2.blendLinear(middle[y1:y2, x1:x2], warped, 1 - weight, weight)
    return middle
