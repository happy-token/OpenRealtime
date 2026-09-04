"""Direct adapter for the official ``silero-vad`` package.

The adapter deliberately does not use Pipecat (or another voice pipeline
framework). It feeds PCM16 mono audio to Silero's official model API and maps
the resulting speech probability onto OpenRealtime's small ``Vad`` contract.

Silero's recurrent model accepts exact windows of 512 samples at 16 kHz or
256 samples at 8 kHz. Incoming transport chunks are therefore buffered until
one or more complete windows are available. Model loading is lazy so importing
the server and constructing its dependency graph do not perform heavyweight
ML initialization; the first audio window initializes the official JIT model.
"""

from __future__ import annotations

import array
import math
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from server.signals.energy_vad import (
    ChunkMeasurement,
    EnergyVadConfig,
    VadObservation,
    _OnsetEotTracker,
)
from server.turn_policy.signals import Signal

_FRAME_SAMPLES = {8000: 256, 16000: 512}


class _SileroModel(Protocol):
    def __call__(self, samples: Any, sample_rate_hz: int) -> Any: ...

    def reset_states(self) -> None: ...


class SileroVad:
    """OpenRealtime ``Vad`` conformer backed by Silero's official model.

    ``model`` and ``tensor_factory`` are dependency-injection seams for unit
    tests and alternative official runtimes. Production callers normally omit
    both, which uses ``silero_vad.load_silero_vad()`` and a float32 Torch
    tensor exactly as documented by Silero.
    """

    def __init__(
        self,
        config: EnergyVadConfig | None = None,
        *,
        threshold: float = 0.5,
        model: _SileroModel | None = None,
        tensor_factory: Callable[[Sequence[float]], Any] | None = None,
        model_loader: Callable[[], _SileroModel] | None = None,
    ) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1")

        self._tracker = _OnsetEotTracker(config or EnergyVadConfig())
        self._threshold = threshold
        self._model = model
        self._tensor_factory = tensor_factory
        self._model_loader = model_loader
        self._pending_samples = array.array("h")
        self._sample_rate_hz: int | None = None
        self._lock = threading.RLock()

    def measure_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> ChunkMeasurement | None:
        """Run direct Silero inference without mutating the turn tracker.

        The Silero model itself is recurrent, so feeding audio necessarily
        advances its inference state. "Without mutating" here refers to the
        OpenRealtime onset/EoT tracker, matching the ``Vad`` protocol's use for
        overlap detection while the assistant is speaking.
        """

        with self._lock:
            return self._measure_chunk_locked(pcm16, sample_rate_hz=sample_rate_hz)

    def process_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> Signal | None:
        observation = self.observe_chunk(pcm16, sample_rate_hz=sample_rate_hz)
        return observation.signal if observation is not None else None

    def observe_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> VadObservation | None:
        with self._lock:
            measurement = self._measure_chunk_locked(pcm16, sample_rate_hz=sample_rate_hz)
            if measurement is None:
                return None
            signal = self._tracker.advance(measurement)
            return VadObservation(
                measurement=measurement,
                signal=signal,
                silence_ms=(
                    self._tracker.last_eot_silence_ms
                    if signal is Signal.USER_EOT_CONFIRMED
                    else 0.0
                ),
            )

    def resume_user_utterance(self) -> None:
        """Re-arm OpenRealtime's turn tracker after a deferred EoT or barge-in."""

        with self._lock:
            self._tracker.resume_user_utterance()

    def close(self) -> None:
        """Release buffered audio and reset the official recurrent model."""

        with self._lock:
            self._pending_samples = array.array("h")
            self._sample_rate_hz = None
            if self._model is not None:
                self._model.reset_states()

    def _measure_chunk_locked(
        self, pcm16: bytes, *, sample_rate_hz: int
    ) -> ChunkMeasurement | None:
        frame_samples = _FRAME_SAMPLES.get(sample_rate_hz)
        if frame_samples is None:
            raise ValueError("Silero VAD sample_rate_hz must be 8000 or 16000")
        if len(pcm16) % 2:
            raise ValueError("pcm16 must contain complete 16-bit samples")
        if not pcm16:
            return None

        self._activate_sample_rate(sample_rate_hz)
        incoming = array.array("h")
        incoming.frombytes(pcm16)
        self._pending_samples.extend(incoming)

        probabilities: list[float] = []
        while len(self._pending_samples) >= frame_samples:
            frame = self._pending_samples[:frame_samples]
            del self._pending_samples[:frame_samples]
            probabilities.append(self._speech_probability(frame, sample_rate_hz))

        if not probabilities:
            return None

        duration_ms = len(probabilities) * frame_samples / sample_rate_hz * 1000
        return ChunkMeasurement(
            is_loud=max(probabilities) >= self._threshold,
            duration_ms=duration_ms,
        )

    def _activate_sample_rate(self, sample_rate_hz: int) -> None:
        if self._sample_rate_hz is None:
            self._sample_rate_hz = sample_rate_hz
            return
        if self._sample_rate_hz == sample_rate_hz:
            return

        self._pending_samples = array.array("h")
        self._sample_rate_hz = sample_rate_hz
        if self._model is not None:
            self._model.reset_states()

    def _speech_probability(self, frame: array.array[int], sample_rate_hz: int) -> float:
        model, tensor_factory = self._ensure_runtime()
        normalized = tuple(sample / 32768.0 for sample in frame)
        result = model(tensor_factory(normalized), sample_rate_hz)
        probability = float(result.item() if callable(getattr(result, "item", None)) else result)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError(f"Silero VAD returned invalid speech probability: {probability!r}")
        return probability

    def _ensure_runtime(
        self,
    ) -> tuple[_SileroModel, Callable[[Sequence[float]], Any]]:
        if self._model is None:
            if self._model_loader is None:
                from silero_vad import load_silero_vad

                self._model_loader = load_silero_vad
            self._model = self._model_loader()

        if self._tensor_factory is None:
            import torch

            self._tensor_factory = lambda values: torch.tensor(values, dtype=torch.float32)

        return self._model, self._tensor_factory
