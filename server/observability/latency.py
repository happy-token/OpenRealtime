"""Deterministic Realtime response latency milestones and acceptance checks."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class LatencyMilestone(StrEnum):
    TURN_ACCEPTED = "turn_accepted"
    ENGINE_STARTED = "engine_started"
    FIRST_TEXT_DELTA = "first_text_delta"
    FIRST_SPEAKABLE_SEGMENT = "first_speakable_segment"
    TTS_REQUESTED = "tts_requested"
    TTS_FIRST_AUDIO = "tts_first_audio"
    FIRST_AUDIO_DELTA = "first_audio_delta"
    FIRST_AUDIO_SENT = "first_audio_sent"
    BARGE_IN_CONFIRMED = "barge_in_confirmed"
    PLAYBACK_STOPPED = "playback_stopped"
    RESPONSE_TERMINAL = "response_terminal"


@dataclass(frozen=True, slots=True)
class ResponseLatencyMetrics:
    response_id: str
    end_of_turn_to_first_audio_ms: int | None
    barge_in_to_stop_ms: int | None


@dataclass(frozen=True, slots=True)
class LatencyAssessment:
    first_audio_p50_target_met: bool | None
    first_audio_p95_target_met: bool | None
    barge_in_target_met: bool | None


@dataclass(frozen=True, slots=True)
class VoiceLatencyTargets:
    first_audio_p50_ms: int = 800
    first_audio_p95_ms: int = 1500
    barge_in_to_stop_ms: int = 200

    def assess(self, metrics: ResponseLatencyMetrics) -> LatencyAssessment:
        first_audio = metrics.end_of_turn_to_first_audio_ms
        barge_in = metrics.barge_in_to_stop_ms
        return LatencyAssessment(
            first_audio_p50_target_met=(
                None if first_audio is None else first_audio < self.first_audio_p50_ms
            ),
            first_audio_p95_target_met=(
                None if first_audio is None else first_audio < self.first_audio_p95_ms
            ),
            barge_in_target_met=(
                None if barge_in is None else barge_in < self.barge_in_to_stop_ms
            ),
        )


class ResponseLatencyTrace:
    def __init__(self, *, response_id: str, generation: int | None = None) -> None:
        if not response_id:
            raise ValueError("response_id must be non-empty")
        if generation is not None and generation < 0:
            raise ValueError("generation must be non-negative")
        self.response_id = response_id
        self.generation = generation
        self._timestamps: dict[LatencyMilestone, float] = {}
        self._observers: list[
            Callable[[ResponseLatencyTrace, LatencyMilestone, float], None]
        ] = []

    def subscribe(
        self,
        observer: Callable[[ResponseLatencyTrace, LatencyMilestone, float], None],
        *,
        replay: bool = True,
    ) -> None:
        self._observers.append(observer)
        if replay:
            for milestone, timestamp in self._timestamps.items():
                observer(self, milestone, timestamp)

    def mark(
        self, milestone: LatencyMilestone, *, at: float | None = None
    ) -> bool:
        if milestone in self._timestamps:
            return False
        timestamp = time.monotonic() if at is None else at
        if self._timestamps and timestamp < max(self._timestamps.values()):
            raise ValueError("latency milestones cannot move backwards")
        self._timestamps[milestone] = timestamp
        for observer in tuple(self._observers):
            observer(self, milestone, timestamp)
        return True

    def snapshot(self) -> ResponseLatencyMetrics:
        return ResponseLatencyMetrics(
            response_id=self.response_id,
            end_of_turn_to_first_audio_ms=self._duration_ms(
                LatencyMilestone.TURN_ACCEPTED,
                LatencyMilestone.FIRST_AUDIO_SENT,
            ),
            barge_in_to_stop_ms=self._duration_ms(
                LatencyMilestone.BARGE_IN_CONFIRMED,
                LatencyMilestone.PLAYBACK_STOPPED,
            ),
        )

    def timestamp(self, milestone: LatencyMilestone) -> float | None:
        return self._timestamps.get(milestone)

    def duration_ms(
        self,
        start: LatencyMilestone,
        end: LatencyMilestone,
    ) -> int | None:
        return self._duration_ms(start, end)

    def _duration_ms(
        self, start: LatencyMilestone, end: LatencyMilestone
    ) -> int | None:
        if start not in self._timestamps or end not in self._timestamps:
            return None
        return round((self._timestamps[end] - self._timestamps[start]) * 1000)
