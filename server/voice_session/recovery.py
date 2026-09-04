"""Semantic Voice Session resume and atomic recovery barriers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from server.voice_session.models import (
    VoiceSessionEvent,
    VoiceSessionIdentity,
    VoiceSessionPhase,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionSnapshot:
    identity: VoiceSessionIdentity
    phase: VoiceSessionPhase
    session_sequence: int
    journal_sequence: int
    generation: int
    active_work_refs: tuple[str, ...] = ()
    pending_confirmation_id: str | None = None
    playback_generation: int | None = None
    played_position_samples: int | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if min(self.session_sequence, self.journal_sequence, self.generation) < 0:
            raise ValueError("Voice Session Snapshot counters must not be negative")
        if self.schema_version < 1:
            raise ValueError("Voice Session Snapshot schema version must be positive")


class VoiceSessionEventTail:
    def __init__(self, *, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("Voice Session event tail capacity must be positive")
        self._events: deque[VoiceSessionEvent] = deque(maxlen=capacity)

    def append(self, event: VoiceSessionEvent) -> None:
        if self._events and event.session_sequence != self._events[-1].session_sequence + 1:
            raise ValueError("Voice Session event tail must be contiguous")
        self._events.append(event)

    def events_after(self, sequence: int) -> tuple[VoiceSessionEvent, ...] | None:
        if sequence < 0:
            raise ValueError("Voice Session event cursor must not be negative")
        if not self._events:
            return ()
        oldest = self._events[0].session_sequence
        latest = self._events[-1].session_sequence
        if sequence < oldest - 1 or sequence > latest:
            return None
        return tuple(event for event in self._events if event.session_sequence > sequence)


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticResumePlan:
    snapshot: VoiceSessionSnapshot | None
    events: tuple[VoiceSessionEvent, ...]
    resume_from_sequence: int


class SemanticResumePlanner:
    def __init__(self, *, event_tail: VoiceSessionEventTail) -> None:
        self._event_tail = event_tail

    def plan(
        self,
        *,
        snapshot: VoiceSessionSnapshot,
        last_session_sequence: int,
    ) -> SemanticResumePlan:
        events = self._event_tail.events_after(last_session_sequence)
        if events is None:
            return SemanticResumePlan(
                snapshot=snapshot,
                events=(),
                resume_from_sequence=snapshot.session_sequence,
            )
        return SemanticResumePlan(
            snapshot=None,
            events=events,
            resume_from_sequence=last_session_sequence,
        )
