"""OpenRealtime-owned digital-human mouth/lip compositing layer.

This module is the replaceable seam that pastes a mouth prediction (or a
derived mouth-openness) back onto an avatar frame.  It deliberately owns its
own composition logic instead of inheriting the upstream LiveTalking
``paste_back_frame`` hard-blit, so OpenRealtime can control the blend strength,
the covered region and the feather without being locked to a LiveTalking
repository file hash.

Two speech modes are supported:

* ``wav2lip``  -- paste a Wav2Lip ``256x256`` face prediction back onto the
  lower face with a configurable blend and an elliptical/soft mask.
* ``energy_draw`` -- drive a soft drawn mouth purely from audio frame energy,
  with no neural inference (a degraded, no-GPU fallback).

The mouth geometry is expressed in the **face-bbox (ROI) normalized frame**
(0..1 relative to the face crop), matching the coordinate space of the Wav2Lip
face prediction and ``coords``.  Both modes resolve it to the correct pixel
position via the avatar's ``coords``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

import numpy as np

__all__ = [
    "CompositionConfig",
    "MaskMode",
    "MouthGeometry",
    "SpeechMode",
    "apply_composition",
    "apply_lower_face_mask",
    "blend_wav2lip_roi",
    "draw_energy_mouth",
]

BBox = tuple[int, int, int, int]


class SpeechMode(str, Enum):
    WAV2LIP = "wav2lip"
    ENERGY_DRAW = "energy_draw"


class MaskMode(str, Enum):
    FULL = "full"
    MOUTH = "mouth"


@dataclass(frozen=True)
class MouthGeometry:
    center_x: float = 0.50
    center_y: float = 0.77
    rx: float = 0.27
    ry: float = 0.055
    ry_open_factor: float = 3.6
    inner_alpha_base: float = 0.30
    inner_alpha_open: float = 0.28
    lip_color_bgr: tuple[int, int, int] = (76, 70, 130)
    lip_alpha_base: float = 0.20
    lip_alpha_open: float = 0.20


@dataclass(frozen=True)
class CompositionConfig:
    speech_mode: SpeechMode = SpeechMode.WAV2LIP
    wav2lip_blend: float = 0.5
    mask_mode: MaskMode = MaskMode.MOUTH
    mask_feather: float = 0.35
    geometry: MouthGeometry = field(default_factory=MouthGeometry)
    fps: int = 25


def _smoothstep(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def apply_lower_face_mask(height: int, width: int, feather: float = 0.35) -> np.ndarray:
    """Soft lower-face mask (in face-crop normalized space)."""
    top = max(1, round(height * 0.4))
    full = max(top + 1, round(height * 0.6))
    edge = max(1, round(min(height, width) * feather))
    rows = np.arange(height, dtype=np.float32)[:, None]
    cols = np.arange(width, dtype=np.float32)[None, :]
    vertical_in = _smoothstep((rows - top) / (full - top))
    vertical_out = _smoothstep((height - 1 - rows) / edge)
    horizontal_in = _smoothstep(cols / edge)
    horizontal_out = _smoothstep((width - 1 - cols) / edge)
    return vertical_in * vertical_out * horizontal_in * horizontal_out


@lru_cache(maxsize=128)
def _mouth_mask(
    height: int,
    width: int,
    geometry: MouthGeometry,
    feather: float,
) -> np.ndarray:
    """Build a stable mouth core plus an asymmetric open-mouth feather.

    ``geometry.ry`` describes the closed lip band. Wav2Lip can move pixels
    several lip-heights below that band when the mouth opens, so using ``ry``
    as the complete mask radius clips away the generated articulation. The
    lower radius therefore uses ``ry_open_factor`` while the upper radius is
    capped to avoid blending the nose and upper face.
    """

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx = geometry.center_x * width
    cy = geometry.center_y * height
    rx = max(geometry.rx * width, 1.0)
    closed_ry = max(geometry.ry * height, 1.0)
    upper_ry = closed_ry * min(max(geometry.ry_open_factor, 1.0), 2.0)
    lower_ry = closed_ry * max(geometry.ry_open_factor, 1.0)
    vertical_radius = np.where(yy < cy, upper_ry, lower_ry)
    distance = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / vertical_radius) ** 2)

    feather_width = float(np.clip(feather, 0.01, 1.0))
    core_boundary = 1.0 - feather_width
    return (1.0 - _smoothstep((distance - core_boundary) / feather_width)).astype(np.float32)


def blend_wav2lip_roi(
    original: np.ndarray,
    prediction: np.ndarray,
    *,
    blend: float = 0.5,
    mask_mode: MaskMode = MaskMode.MOUTH,
    feather: float = 0.35,
    geometry: MouthGeometry | None = None,
) -> np.ndarray:
    """Paste a same-sized Wav2Lip prediction into its original face ROI.

    ``blend`` (0..1) controls how much the prediction replaces the original in
    the covered region; ``mask_mode`` selects the covered region (``MOUTH``
    uses the mouth ellipse, sized from ``geometry`` in ROI-normalized space).
    """
    if original.shape != prediction.shape or original.ndim != 3 or original.shape[2] != 3:
        raise ValueError("original and prediction must be same-sized HxWx3 images")
    height, width = original.shape[:2]
    geometry = geometry or MouthGeometry()
    if mask_mode is MaskMode.MOUTH:
        mask = _mouth_mask(height, width, geometry, feather)
    else:
        mask = apply_lower_face_mask(height, width, feather)
    amount = float(np.clip(blend, 0.0, 1.0))
    if amount == 0:
        return original.copy()
    # Mixing two differently shaped lip contours leaves the closed source lip
    # across the generated mouth cavity. Align only the source mouth texture
    # before the 0.6 mix; apply the spatial feather once, against the base frame.
    source = _align_source_mouth(original, prediction, mask, amount) if mask_mode is MaskMode.MOUTH else original
    import cv2
    mouth = cv2.addWeighted(source, 1.0 - amount, prediction, amount, 0)
    return cv2.blendLinear(original, mouth, 1.0 - mask, mask)


def _align_source_mouth(original: np.ndarray, prediction: np.ndarray,
                        mask: np.ndarray, amount: float) -> np.ndarray:
    """Backward optical flow on a small mouth crop, never on the whole face.

    The analysis grid is bounded independently of output resolution. There is
    no temporal averaging of predictions: each phoneme keeps its own shape.
    """
    import cv2

    rows, columns = np.nonzero(mask > 0)
    if not len(rows):
        return original
    height, width = original.shape[:2]
    y1, y2 = max(0, int(rows.min()) - 4), min(height, int(rows.max()) + 5)
    x1, x2 = max(0, int(columns.min()) - 4), min(width, int(columns.max()) + 5)
    crop_width, crop_height = x2 - x1, y2 - y1
    analysis_width = min(96, crop_width)
    analysis_height = max(8, round(crop_height * analysis_width / crop_width))
    source = cv2.resize(original[y1:y2, x1:x2], (analysis_width, analysis_height))
    target = cv2.resize(prediction[y1:y2, x1:x2], (analysis_width, analysis_height))
    flow = cv2.calcOpticalFlowFarneback(
        cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), cv2.cvtColor(source, cv2.COLOR_BGR2GRAY),
        None, 0.5, 3, 9, 6, 5, 1.1, 0,
    )
    flow = cv2.resize(flow, (crop_width, crop_height))
    flow[:, :, 0] *= crop_width / analysis_width
    flow[:, :, 1] *= crop_height / analysis_height
    flow = np.clip(flow, -min(height, width) * 0.06, min(height, width) * 0.06)
    flow *= min(1.0, amount / 0.6)
    yy, xx = np.mgrid[y1:y2, x1:x2].astype(np.float32)
    aligned = original.copy()
    aligned[y1:y2, x1:x2] = cv2.remap(original, xx + flow[:, :, 0], yy + flow[:, :, 1],
                                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    return aligned


def _mouth_pixels(geometry: MouthGeometry, bbox: BBox | None, frame_shape: tuple[int, int]) -> tuple[float, float, float, float]:
    height, width = frame_shape
    if bbox is None:
        cx, cy = geometry.center_x * width, geometry.center_y * height
        rx, ry = geometry.rx * width, geometry.ry * height
        return cx, cy, rx, ry
    y1, y2, x1, x2 = bbox
    cx = x1 + geometry.center_x * (x2 - x1)
    cy = y1 + geometry.center_y * (y2 - y1)
    rx = geometry.rx * (x2 - x1)
    ry = geometry.ry * (y2 - y1)
    return cx, cy, rx, ry


def draw_energy_mouth(
    frame_bgr: np.ndarray,
    openness: float,
    *,
    geometry: MouthGeometry,
    bbox: BBox | None = None,
) -> np.ndarray:
    """Draw a soft, feathered mouth onto a closed-mouth base frame at the mouth.

    ``openness`` (0..1) scales the mouth height and darkness; no neural
    inference is involved.  ``bbox`` (the avatar's ``coords`` face box, in
    y1,y2,x1,x2 order) resolves the mouth geometry from face-crop space to the
    full-frame pixel position.
    """
    open_amount = float(np.clip(openness, 0.0, 1.0))
    if open_amount <= 0.02:
        return frame_bgr
    height, width = frame_bgr.shape[:2]
    cx, cy, rx, ry = _mouth_pixels(geometry, bbox, (height, width))
    rx = max(4.0, rx * (1.0 + 0.12 * open_amount))
    ry = max(2.0, ry * (geometry.ry_open_factor * open_amount + (1.0 - open_amount)))

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dist = np.sqrt(((xx - cx) / max(rx, 1.0)) ** 2 + ((yy - cy) / max(ry, 1.0)) ** 2)
    core = np.clip(1.0 - dist, 0.0, 1.0) ** 2
    dark = np.array([10, 8, 22], dtype=np.float32)
    inner_alpha = geometry.inner_alpha_base + geometry.inner_alpha_open * open_amount
    out = frame_bgr.astype(np.float32).copy()
    mix = core[:, :, None] * inner_alpha
    out = out * (1.0 - mix) + dark[None, None, :] * mix

    lip = np.asarray(geometry.lip_color_bgr, dtype=np.float32)
    lip_band = np.exp(-(((yy - (cy - ry * 0.50)) / max(ry * 0.30, 1.0)) ** 2))
    lip_band *= np.clip(1.0 - np.abs(xx - cx) / (rx * 0.92), 0.0, 1.0)
    lip_alpha = (geometry.lip_alpha_base + geometry.lip_alpha_open * open_amount) * lip_band[:, :, None]
    out = out * (1.0 - lip_alpha) + lip[None, None, :] * lip_alpha
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def apply_composition(
    frame_bgr: np.ndarray,
    inference: np.ndarray | float,
    config: CompositionConfig,
    *,
    bbox: BBox | None = None,
) -> np.ndarray:
    """Apply the configured composition to one frame.

    ``inference`` is either a Wav2Lip prediction (HxWx3, sized to the bbox ROI
    or the full frame when ``bbox`` is None) for ``wav2lip`` mode, or a scalar
    openness (0..1) for ``energy_draw`` mode.
    """
    if config.speech_mode is SpeechMode.ENERGY_DRAW:
        openness = float(inference)
        return draw_energy_mouth(frame_bgr, openness, geometry=config.geometry, bbox=bbox)
    prediction = np.asarray(inference, dtype=np.uint8)
    if bbox is None:
        return blend_wav2lip_roi(
            frame_bgr,
            prediction,
            blend=config.wav2lip_blend,
            mask_mode=config.mask_mode,
            feather=config.mask_feather,
            geometry=config.geometry,
        )
    y1, y2, x1, x2 = bbox
    roi = frame_bgr[y1:y2, x1:x2]
    blended = blend_wav2lip_roi(
        roi,
        prediction,
        blend=config.wav2lip_blend,
        mask_mode=config.mask_mode,
        feather=config.mask_feather,
        geometry=config.geometry,
    )
    out = frame_bgr.copy()
    out[y1:y2, x1:x2] = blended
    return out
