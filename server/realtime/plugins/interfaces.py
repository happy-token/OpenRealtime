"""Distinct interfaces for processor, analyzer, and sink plugin slots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from server.realtime.plugins.context import CapabilityContext
from server.realtime.protocol.audio import AudioFrame


class AudioProcessorSession(Protocol):
    async def process(self, audio: AudioFrame) -> AudioFrame: ...

    async def close(self) -> None: ...


class AudioProcessorBinding(Protocol):
    async def open(
        self,
        *,
        context: CapabilityContext,
        config: dict[str, object],
    ) -> AudioProcessorSession: ...


class SpeakerDecision(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeakerEvidence:
    speaker_profile_id: str
    confidence: float
    audio_start_us: int
    audio_end_us: int
    model_version: str
    enrollment_version: str
    decision: SpeakerDecision

    def __post_init__(self) -> None:
        if not self.speaker_profile_id or not self.model_version or not self.enrollment_version:
            raise ValueError("speaker evidence identity and versions must be non-empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("speaker evidence confidence must be between zero and one")
        if self.audio_start_us < 0 or self.audio_end_us <= self.audio_start_us:
            raise ValueError("speaker evidence audio range must be positive")


AudioAnalysisEvidence = SpeakerEvidence


class AudioAnalyzerSession(Protocol):
    async def analyze(self, audio: AudioFrame) -> tuple[AudioAnalysisEvidence, ...]: ...

    async def close(self) -> None: ...


class AudioAnalyzerBinding(Protocol):
    async def open(
        self,
        *,
        context: CapabilityContext,
        config: dict[str, object],
    ) -> AudioAnalyzerSession: ...


class AudioSinkSession(Protocol):
    async def consume(self, audio: AudioFrame) -> None: ...

    async def close(self) -> None: ...


class AudioSinkBinding(Protocol):
    async def open(
        self,
        *,
        context: CapabilityContext,
        config: dict[str, object],
    ) -> AudioSinkSession: ...
