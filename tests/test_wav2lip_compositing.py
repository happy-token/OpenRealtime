import numpy as np

from scripts.wav2lip_compositing import blend_wav2lip_roi


def test_blend_preserves_original_upper_face_and_uses_predicted_mouth_center() -> None:
    original = np.full((20, 20, 3), 20, dtype=np.uint8)
    prediction = np.full((20, 20, 3), 220, dtype=np.uint8)

    blended = blend_wav2lip_roi(original, prediction)

    assert np.array_equal(blended[:8], original[:8])
    assert np.array_equal(blended[14, 10], prediction[14, 10])
    assert np.array_equal(blended[:, 0], original[:, 0])
    assert np.array_equal(blended[:, -1], original[:, -1])


def test_blend_feathers_the_transition_instead_of_creating_a_hard_seam() -> None:
    original = np.zeros((20, 20, 3), dtype=np.uint8)
    prediction = np.full((20, 20, 3), 200, dtype=np.uint8)

    blended = blend_wav2lip_roi(original, prediction)

    assert np.all((blended[10, 10] > 0) & (blended[10, 10] < 200))
    assert np.array_equal(blended[14, 10], prediction[14, 10])
