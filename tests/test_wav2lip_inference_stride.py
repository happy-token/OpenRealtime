import pytest
import torch

from scripts.wav2lip_inference_stride import infer_wav2lip_batch


class RecordingModel:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def __call__(self, audio: torch.Tensor, faces: torch.Tensor) -> torch.Tensor:
        self.batch_sizes.append(len(audio))
        return faces + audio


def test_stride_one_preserves_full_quality_model_output() -> None:
    model = RecordingModel()
    audio = torch.tensor([[1.0], [2.0], [3.0], [4.0]])
    faces = torch.tensor([[10.0], [20.0], [30.0], [40.0]])

    output = infer_wav2lip_batch(model, audio, faces, inference_stride=1)

    assert model.batch_sizes == [4]
    assert output.tolist() == [[11.0], [22.0], [33.0], [44.0]]


def test_stride_two_infers_keyframes_and_interpolates_a_full_rate_batch() -> None:
    model = RecordingModel()
    audio = torch.tensor([[0.0], [1.0], [2.0], [3.0]])
    faces = torch.tensor([[0.0], [10.0], [20.0], [30.0]])

    output = infer_wav2lip_batch(model, audio, faces, inference_stride=2)

    assert model.batch_sizes == [2]
    assert output.tolist() == [[0.0], [11.0], [22.0], [22.0]]


def test_inference_stride_rejects_mismatched_input_batches() -> None:
    with pytest.raises(ValueError, match="same non-empty batch"):
        infer_wav2lip_batch(
            RecordingModel(),
            torch.zeros(4, 1),
            torch.zeros(3, 1),
            inference_stride=2,
        )
