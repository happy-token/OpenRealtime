import numpy as np
import pytest

pytest.importorskip("cv2")

from server.avatar_compositing import CompositionConfig, MaskMode, MouthGeometry, apply_composition


def test_default_wav2lip_composition_preserves_face_and_exposes_open_mouth() -> None:
    original = np.full((100, 100, 3), 20, dtype=np.uint8)
    prediction = np.full((100, 100, 3), 220, dtype=np.uint8)
    config = CompositionConfig()

    composed = apply_composition(original, prediction, config)

    assert config.wav2lip_blend == 0.5
    assert config.mask_mode is MaskMode.MOUTH
    assert np.array_equal(composed[74, 50], np.full(3, 120, dtype=np.uint8))
    assert np.all(composed[85, 50] > original[85, 50])
    assert np.array_equal(composed[20, 50], original[20, 50])
    assert np.array_equal(composed[74, 5], original[74, 5])


def test_wav2lip_mouth_mask_uses_open_height_below_the_lips() -> None:
    original = np.zeros((200, 200, 3), dtype=np.uint8)
    prediction = np.full_like(original, 200)
    geometry = MouthGeometry(center_y=0.6, ry=0.05, ry_open_factor=3.6)

    composed = apply_composition(
        original,
        prediction,
        CompositionConfig(geometry=geometry),
    )

    closed_lip_radius = geometry.ry * original.shape[0]
    open_mouth_y = round(geometry.center_y * original.shape[0] + closed_lip_radius * 2)
    assert np.all(composed[open_mouth_y, 100] > 0)


def test_motion_midpoint_leaves_the_upper_face_unwarped():
    from server.avatar_compositing.motion import interpolate_mouth
    rng = np.random.default_rng(9)
    left = rng.integers(0, 256, (100, 100, 3), dtype=np.uint8)
    right = np.roll(left, 3, axis=1)
    middle = interpolate_mouth(left, right, MouthGeometry())
    import cv2
    np.testing.assert_array_equal(middle[:50], cv2.addWeighted(left, .5, right, .5, 0)[:50])


def test_mouth_tracking_preserves_custom_geometry_when_texture_is_untrackable():
    from server.avatar_compositing.motion import track_mouth_geometry
    geometry = MouthGeometry(center_x=.4, center_y=.7, rx=.22)
    tracked = track_mouth_geometry([np.zeros((100, 100, 3), dtype=np.uint8)] * 3, geometry)
    assert tracked == [geometry] * 3
