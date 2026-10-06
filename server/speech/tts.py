"""TtsEngine Protocol: text-to-speech for realtime capabilities.

This module ships the Protocol plus SilentTtsEngine, a deterministic
stand-in with no network dependency (the "EchoLlmClient of TTS"), for
tests and demos. See speech/doubao_tts.py for a real conformer, and
CONTEXT.md — TtsEngine.

StreamingTtsEngine is a separate, opt-in Protocol for callers that need
chunked audio delivery with true mid-playback cancellation (see CONTEXT.md —
StreamingTtsEngine). It is deliberately not a method added to TtsEngine,
so the existing whole-utterance path and its conformers stay unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class SynthesizedAudio:
    pcm16: bytes
    sample_rate_hz: int


@dataclass(frozen=True)
class SynthesizedAudioChunk:
    pcm16: bytes
    sample_rate_hz: int
    is_final: bool
    spoken_text: str | None = None
    spoken_start_us: int | None = None
    spoken_end_us: int | None = None
    # Words may be pronunciation renderings; original sentence text is an
    # anchor for captions. Its time range must be explicitly on the whole
    # speech clock before it can be used as sentence playback evidence.
    sentence_text: str | None = None
    sentence_duration_us: int | None = None
    sentence_start_us: int | None = None
    sentence_timebase: Literal["speech"] | None = None


class TtsEngine(Protocol):
    async def synthesize(self, text: str) -> SynthesizedAudio: ...


class StreamingTtsEngine(Protocol):
    def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]: ...


class DuplexStreamingTtsEngine(Protocol):
    """Stream incremental text in while synthesized audio streams out."""

    def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]: ...


@dataclass(frozen=True)
class TtsSessionConfig:
    voice: str
    speech_rate: int = 0
    dialect: str = ""


class ConfigurableTtsEngine(Protocol):
    def configure(self, config: TtsSessionConfig) -> None: ...


class SilentTtsEngine:
    """Deterministic stand-in with no network dependency — for tests and demos.

    Always returns empty PCM16 audio at the given sample rate, regardless
    of the input text. Satisfies both TtsEngine and StreamingTtsEngine.
    """

    def __init__(self, sample_rate_hz: int = 24000) -> None:
        self._sample_rate_hz = sample_rate_hz

    async def synthesize(self, text: str) -> SynthesizedAudio:
        return SynthesizedAudio(pcm16=b"", sample_rate_hz=self._sample_rate_hz)

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        yield SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=self._sample_rate_hz, is_final=True)
