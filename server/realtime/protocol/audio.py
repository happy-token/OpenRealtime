"""Negotiated audio frames carried on the realtime media timeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AudioEncoding(StrEnum):
    PCM_S16LE = "pcm_s16le"
    PCM_F32LE = "pcm_f32le"
    OPUS = "opus"


@dataclass(frozen=True, slots=True)
class AudioFrame:
    stream_id: str
    sequence: int
    timestamp_us: int
    duration_us: int
    encoding: AudioEncoding
    sample_rate_hz: int
    channels: int
    data: bytes

    def __post_init__(self) -> None:
        if not self.stream_id:
            raise ValueError("audio stream identity must be non-empty")
        if self.sequence < 0 or self.timestamp_us < 0:
            raise ValueError("audio sequence and timestamp must be non-negative")
        if self.duration_us <= 0 or self.sample_rate_hz <= 0 or self.channels <= 0:
            raise ValueError("audio duration, sample rate, and channels must be positive")
        if not self.data:
            raise ValueError("audio frame data must be non-empty")

    @property
    def end_timestamp_us(self) -> int:
        return self.timestamp_us + self.duration_us
