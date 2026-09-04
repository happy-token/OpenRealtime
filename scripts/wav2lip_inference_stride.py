"""Frame-strided Wav2Lip inference with a full-rate output batch."""

from __future__ import annotations

from typing import Protocol

import torch


class Wav2LipModel(Protocol):
    def __call__(self, audio: torch.Tensor, faces: torch.Tensor) -> torch.Tensor: ...


def infer_wav2lip_batch(
    model: Wav2LipModel,
    audio: torch.Tensor,
    faces: torch.Tensor,
    *,
    inference_stride: int = 1,
) -> torch.Tensor:
    """Run Wav2Lip while preserving one prediction for every output frame."""

    if len(audio) == 0 or len(audio) != len(faces):
        raise ValueError("audio and faces must have the same non-empty batch")
    if inference_stride not in (1, 2):
        raise ValueError("inference_stride must be 1 or 2")
    if inference_stride == 1:
        return model(audio, faces)

    keyframes = model(audio[::inference_stride], faces[::inference_stride])
    expanded = []
    last_keyframe = len(keyframes) - 1
    for frame_index in range(len(audio)):
        left = frame_index // inference_stride
        right = min(left + 1, last_keyframe)
        offset = frame_index % inference_stride
        if offset == 0 or left == right:
            expanded.append(keyframes[left])
        else:
            expanded.append(torch.lerp(keyframes[left], keyframes[right], offset / inference_stride))
    return torch.stack(expanded)
