"""Shared inference/composition path for OpenRealtime's realtime avatar renderer."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import librosa
import numpy as np
import torch
from scipy.signal import lfilter

from scripts.wav2lip_inference_stride import infer_wav2lip_batch
from server.avatar_compositing import CompositionConfig, MouthGeometry, apply_composition
from server.avatar_compositing.motion import interpolate_mouth, track_mouth_geometry

FPS = 25
SAMPLE_RATE = 16000
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS


def mel_spectrogram(pcm: np.ndarray) -> np.ndarray:
    """Native 80 Hz mel grid and normalization used to train Wav2Lip."""
    emphasized = lfilter([1, -0.97], [1], pcm)
    spectrum = np.abs(librosa.stft(emphasized, n_fft=800, hop_length=200, win_length=800))
    basis = librosa.filters.mel(sr=SAMPLE_RATE, n_fft=800, n_mels=80, fmin=55, fmax=7600)
    decibels = 20 * np.log10(np.maximum(1e-5, basis @ spectrum)) - 20
    return np.clip(8 * ((decibels + 100) / 100) - 4, -4, 4).astype(np.float32)


def mel_windows(mel: np.ndarray, start: int, count: int, origin: int = 0) -> np.ndarray:
    # Pad the *tail*, never repeat the last window across the end of a sentence.
    last_end = int((start + count - 1) * 80 / FPS) - origin + 16
    mel = np.pad(mel, ((0, 0), (0, max(0, last_end - mel.shape[1]))), constant_values=-4)
    return np.stack([mel[:, int(i * 80 / FPS) - origin:int(i * 80 / FPS) - origin + 16]
                     for i in range(start, start + count)])


def stream_mel(pcm: np.ndarray, start: int, count: int) -> tuple[np.ndarray, int]:
    """A bounded STFT slice on the utterance's original 200-sample grid.

    Left context preserves pre-emphasis and FFT overlap. No chunk boundary is
    reflected/padded: the caller waits for real lookahead until final arrives.
    """
    origin = max(0, int(start * 80 / FPS) - 4)
    end = (int((start + count) * 80 / FPS) + 16) * 200 + 400
    samples = pcm[origin * 200:end].astype(np.float32) / 32768
    if len(samples) < 800:
        samples = np.pad(samples, (0, 800 - len(samples)))
    return mel_spectrogram(samples), origin


@dataclass
class AvatarFrames:
    root: Path
    full_paths: list[Path]
    faces: list[np.ndarray]
    coords: list[tuple[int, int, int, int]]
    full_frames: list[np.ndarray]
    mouth_geometries: list[MouthGeometry] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path, avatar_id: str, model_size: int, geometry: MouthGeometry | None = None) -> AvatarFrames:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", avatar_id) is None:
            raise ValueError("Invalid avatar ID")
        path = (root / avatar_id).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Avatar must stay within the configured asset root")
        full = sorted((path / "full_imgs").glob("*.png"), key=lambda p: int(p.stem))
        face_paths = sorted((path / "face_imgs").glob("*.png"), key=lambda p: int(p.stem))
        coords = [tuple(row) for row in json.loads((path / "coords.json").read_text())]
        faces = [cv2.imread(str(p)) for p in face_paths]
        if not full or len(full) != len(faces) or len(full) != len(coords):
            raise ValueError("Avatar frames, crops and coordinates must have matching lengths")
        if any(face is None or face.shape != (model_size, model_size, 3) for face in faces):
            raise ValueError("Avatar crop size does not match the loaded model")
        # Decode and size the motion base once, before WebRTC starts. Repeated
        # full-resolution PNG decoding must not consume the 40 ms frame budget.
        full_frames = []
        scaled_coords = []
        for image_path, (y1, y2, x1, x2) in zip(full, coords):
            frame = cv2.imread(str(image_path))
            if frame is None:
                raise ValueError("Unable to decode avatar frame")
            height, width = frame.shape[:2]
            if not (0 <= y1 < y2 <= height and 0 <= x1 < x2 <= width):
                raise ValueError("Face box lies outside its frame")
            scale = min(1.0, 768 / max(height, width))
            target_width = max(2, round(width * scale / 2) * 2)
            target_height = max(2, round(height * scale / 2) * 2)
            full_frames.append(cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA))
            scaled_coords.append((round(y1 * target_height / height), round(y2 * target_height / height),
                                  round(x1 * target_width / width), round(x2 * target_width / width)))
        return cls(path, full, faces, scaled_coords, full_frames, track_mouth_geometry(faces, geometry or MouthGeometry()))

    def index(self, frame_index: int) -> int:
        size = len(self.faces)
        offset = frame_index % (2 * size)
        return offset if offset < size else 2 * size - offset - 1

    def frame(self, frame_index: int) -> np.ndarray:
        return self.full_frames[self.index(frame_index)]


class AvatarRenderer:
    def __init__(self, checkpoint: Path, model_size: int = 256, *, stride: int = 2,
                 config: CompositionConfig | None = None):
        if stride not in (1, 2):
            raise ValueError("stride must be 1 or 2")
        self.model: torch.nn.Module
        if model_size == 256:
            from server.avatar_compositing.models.wav2lip_v2 import Wav2Lip as Wav2Lip256
            self.model = Wav2Lip256()
        elif model_size == 96:
            from server.avatar_compositing.models.wav2lip import Wav2Lip as Wav2Lip96
            self.model = Wav2Lip96()
        else:
            raise ValueError("model_size must be 96 or 256")
        self.device = torch.device("mps" if torch.backends.mps.is_available()
                                   else "cuda" if torch.cuda.is_available() else "cpu")
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)["state_dict"]
        self.model.load_state_dict({key.removeprefix("module."): value for key, value in state.items()})
        self.model = self.model.to(self.device).eval()
        if self.device.type != "cpu" and model_size == 256:
            self.model.half()
        self.dtype = next(self.model.parameters()).dtype
        self.stride = stride
        self.config = config or CompositionConfig()
        self.model_size = model_size

    @torch.inference_mode()
    def predict(self, faces: list[np.ndarray], windows: np.ndarray, *, keyframes_only: bool = False) -> np.ndarray:
        images = np.asarray(faces)
        masked = images.copy()
        masked[:, self.model_size // 2:] = 0
        inputs = np.concatenate((masked, images), axis=3).astype(np.float32) / 255
        face_tensor = torch.as_tensor(inputs.transpose(0, 3, 1, 2), dtype=self.dtype, device=self.device)
        audio_tensor = torch.as_tensor(windows[:, None], dtype=self.dtype, device=self.device)
        prediction = infer_wav2lip_batch(self.model, audio_tensor, face_tensor,
                                         inference_stride=1 if keyframes_only else self.stride)
        return np.clip(np.rint(prediction.float().cpu().numpy().transpose(0, 2, 3, 1) * 255), 0, 255).astype(np.uint8)

    def render_batch(self, avatar: AvatarFrames, mel: np.ndarray, audio_start: int,
                     frame_start: int, count: int,
                     carry: dict[int, np.ndarray] | None = None, *, mel_origin: int = 0) -> tuple[list[np.ndarray], float]:
        started = time.perf_counter()
        predictions: list[np.ndarray] | np.ndarray
        indices = [avatar.index(frame_start + offset) for offset in range(count)]
        if self.stride == 2 and carry is not None:
            # Carry the lookahead keyframe across batches. Previously each
            # batch repeated its last keyframe, causing an 80 ms hold every
            # four output frames. This still infers just one new key per two
            # output frames after the initial lookahead.
            offsets = list(range(0, count + 1, 2))
            missing = [offset for offset in offsets if frame_start + offset not in carry]
            if missing:
                windows = np.concatenate([mel_windows(mel, audio_start + offset, 1, mel_origin) for offset in missing])
                keys = self.predict([avatar.faces[avatar.index(frame_start + offset)] for offset in missing],
                                    windows, keyframes_only=True)
                carry.update({frame_start + offset: key for offset, key in zip(missing, keys)})
            predictions = []
            for offset in range(count):
                left = carry[frame_start + offset - offset % 2]
                geometry = avatar.mouth_geometries[indices[offset]] if avatar.mouth_geometries else self.config.geometry
                predictions.append(left if offset % 2 == 0 else interpolate_mouth(
                    left, carry[frame_start + offset + 1], geometry))
            following = carry.get(frame_start + count)
            carry.clear()
            if following is not None:
                carry[frame_start + count] = following
        else:
            predictions = self.predict([avatar.faces[i] for i in indices], mel_windows(mel, audio_start, count, mel_origin))
        frames = []
        for offset, (index, prediction) in enumerate(zip(indices, predictions)):
            y1, y2, x1, x2 = avatar.coords[index]
            resized = cv2.resize(prediction, (x2 - x1, y2 - y1))
            config = replace(self.config, geometry=avatar.mouth_geometries[index]) if avatar.mouth_geometries else self.config
            # One composition only, against the original frame for THIS output index.
            frames.append(apply_composition(avatar.frame(frame_start + offset), resized,
                                            config, bbox=(y1, y2, x1, x2)))
        return frames, time.perf_counter() - started
