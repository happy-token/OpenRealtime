"""Low-cost compositing for pasting Wav2Lip predictions into prepared video frames."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def _smoothstep(values: NDArray[np.float32]) -> NDArray[np.float32]:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _lower_face_mask(height: int, width: int) -> NDArray[np.float32]:
    top = max(1, round(height * 0.4))
    full = max(top + 1, round(height * 0.6))
    edge = max(1, round(min(height, width) * 0.1))

    rows = np.arange(height, dtype=np.float32)[:, None]
    columns = np.arange(width, dtype=np.float32)[None, :]
    vertical_in = _smoothstep((rows - top) / (full - top))
    vertical_out = _smoothstep((height - 1 - rows) / edge)
    horizontal_in = _smoothstep(columns / edge)
    horizontal_out = _smoothstep((width - 1 - columns) / edge)
    return vertical_in * vertical_out * horizontal_in * horizontal_out


def blend_wav2lip_roi(
    original: NDArray[np.uint8],
    prediction: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    """Blend one resized Wav2Lip prediction into its same-sized original face ROI."""

    if original.shape != prediction.shape or original.ndim != 3 or original.shape[2] != 3:
        raise ValueError("original and prediction must be same-sized HxWx3 images")

    mask = _lower_face_mask(original.shape[0], original.shape[1])[:, :, None]
    blended = original.astype(np.float32) * (1.0 - mask) + prediction.astype(np.float32) * mask
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)
