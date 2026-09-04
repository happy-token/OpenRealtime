"""Vad Protocol, plus EnergyVad: a minimal RMS-threshold voice-activity
signal source that ships as its deterministic, no-dependency default
conformer.

Feeds Turn Policy with USER_SPEECH_ONSET/USER_EOT_CONFIRMED (and, when
`hesitation_silence_ms` is configured, USER_HESITATION/USER_RESUMED) signals
from raw PCM16 audio, treating sustained silence as end-of-turn. EnergyVad is
the framework's shipped minimal default — not a production-grade VAD or
semantic end-of-turn model (no noise robustness). Real deployments should
plug in a proper VAD/semantic EoT model as the Turn Policy signal source
through the `Vad` protocol; see CONTEXT.md — Turn Policy.

`measure_chunk` is exposed separately from the onset/EoT state machine so a
realtime engine can reuse the same loudness computation to detect overlapping
audio while the assistant is in SPEAK/DUAL, without perturbing
the onset/EoT bookkeeping below (which only tracks the user's own
LISTEN-side utterance).
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass
from typing import Protocol

from server.turn_policy.signals import Signal


@dataclass(frozen=True)
class ChunkMeasurement:
    is_loud: bool
    duration_ms: float


@dataclass(frozen=True)
class VadObservation:
    """One-pass VAD result so callers never run a recurrent model twice."""

    measurement: ChunkMeasurement
    signal: Signal | None
    silence_ms: float = 0.0


class Vad(Protocol):
    def observe_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> VadObservation | None: ...

    def process_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> Signal | None: ...

    def measure_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> ChunkMeasurement | None: ...

    def resume_user_utterance(self) -> None:
        """Re-arm the silence timer for an utterance the Kernel has decided is
        not over after all.

        `process_chunk` commits its own `_speaking`/`_silence_ms` reset as a
        side effect of returning USER_EOT_CONFIRMED, so a caller that declines
        to act on that signal leaves the tracker convinced the user stopped
        talking — and no further USER_EOT_CONFIRMED can ever fire unless the
        user speaks again. Two Kernel paths need to decline: a deferred
        semantic end-of-turn (ADR-0013/0021) and a confirmed barge-in (τ9,
        ADR-0015). See ADR-0037.
        """
        ...


@dataclass(frozen=True)
class EnergyVadConfig:
    energy_threshold: float = 500.0
    silence_duration_ms: float = 600.0
    speech_onset_duration_ms: float = 0.0
    """Consecutive speech required before onset; zero preserves immediate onset."""
    hesitation_silence_ms: float | None = None
    """Shorter silence threshold that emits USER_HESITATION instead of
    USER_EOT_CONFIRMED. None (default) disables hesitation/resume detection
    entirely — silence accumulates straight toward EoT as before. Must be
    less than `silence_duration_ms` when set."""


class _OnsetEotTracker:
    """Turns a stream of loud/quiet ChunkMeasurements into
    onset/hesitation/resume/EoT Signals, given a EnergyVadConfig's silence
    thresholds. Factored out of EnergyVad so a different loudness detector
    can reuse the same turn-taking
    bookkeeping instead of duplicating this state machine."""

    def __init__(self, config: EnergyVadConfig) -> None:
        if config.speech_onset_duration_ms < 0:
            raise ValueError("speech_onset_duration_ms must be non-negative")
        self._config = config
        self._speaking = False
        self._onset_ms = 0.0
        self._silence_ms = 0.0
        self._hesitated = False
        self._last_eot_silence_ms = 0.0

    @property
    def last_eot_silence_ms(self) -> float:
        return self._last_eot_silence_ms

    def advance(self, measurement: ChunkMeasurement) -> Signal | None:
        self._last_eot_silence_ms = 0.0
        if measurement.is_loud:
            self._silence_ms = 0.0
            if not self._speaking:
                self._onset_ms += measurement.duration_ms
                if self._onset_ms < self._config.speech_onset_duration_ms:
                    return None
                self._speaking = True
                self._onset_ms = 0.0
                self._hesitated = False
                return Signal.USER_SPEECH_ONSET
            if self._hesitated:
                self._hesitated = False
                return Signal.USER_RESUMED
            return None

        if not self._speaking:
            self._onset_ms = 0.0
            return None

        self._silence_ms += measurement.duration_ms
        if self._silence_ms >= self._config.silence_duration_ms:
            self._last_eot_silence_ms = self._silence_ms
            self._speaking = False
            self._onset_ms = 0.0
            self._silence_ms = 0.0
            self._hesitated = False
            return Signal.USER_EOT_CONFIRMED

        hesitation_threshold = self._config.hesitation_silence_ms
        if (
            hesitation_threshold is not None
            and not self._hesitated
            and self._silence_ms >= hesitation_threshold
        ):
            self._hesitated = True
            return Signal.USER_HESITATION
        return None

    def resume_user_utterance(self) -> None:
        """See Vad.resume_user_utterance. Grants the utterance a fresh
        `silence_duration_ms` window rather than restoring the elapsed silence,
        so the caller's next EoT is a genuine new silence timeout rather than
        one that re-fires on the very next quiet chunk.

        `_hesitated` must be cleared too: on the barge-in path the tracker was
        never advanced during SPEAK/DUAL (those only call `measure_chunk`), so
        a stale `True` here would make the next loud chunk emit USER_RESUMED
        instead of continuing the utterance silently.
        """
        self._speaking = True
        self._onset_ms = 0.0
        self._silence_ms = 0.0
        self._hesitated = False


class EnergyVad:
    def __init__(self, config: EnergyVadConfig | None = None) -> None:
        self._config = config or EnergyVadConfig()
        self._tracker = _OnsetEotTracker(self._config)

    def measure_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> ChunkMeasurement | None:
        """Pure loudness/duration read for one PCM16 mono chunk; no state mutation."""
        samples = array.array("h")
        samples.frombytes(pcm16)
        if not samples:
            return None

        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        duration_ms = len(samples) / sample_rate_hz * 1000
        return ChunkMeasurement(is_loud=rms >= self._config.energy_threshold, duration_ms=duration_ms)

    def process_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> Signal | None:
        """Feed one PCM16 mono chunk; returns a Turn Policy signal, or None."""
        observation = self.observe_chunk(pcm16, sample_rate_hz=sample_rate_hz)
        return observation.signal if observation is not None else None

    def observe_chunk(self, pcm16: bytes, *, sample_rate_hz: int) -> VadObservation | None:
        """Return loudness and tracker signal from the same measurement."""
        measurement = self.measure_chunk(pcm16, sample_rate_hz=sample_rate_hz)
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
        """See Vad.resume_user_utterance."""
        self._tracker.resume_user_utterance()
