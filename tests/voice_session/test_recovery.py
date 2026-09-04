from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.voice_session import (
    VoiceSessionIdentity,
    VoiceSessionPhase,
    VoiceSessionPhaseChanged,
)
from server.voice_session.recovery import (
    SemanticResumePlanner,
    VoiceSessionEventTail,
    VoiceSessionSnapshot,
)


def identity() -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )


def phase_event(sequence: int, to_phase: VoiceSessionPhase) -> VoiceSessionPhaseChanged:
    return VoiceSessionPhaseChanged(
        event_id=f"event-{sequence}",
        identity=identity(),
        session_sequence=sequence,
        occurred_at=datetime.now(UTC),
        from_phase=VoiceSessionPhase.STARTING,
        to_phase=to_phase,
    )


def test_resume_uses_snapshot_when_the_client_cursor_falls_behind_the_event_tail() -> None:
    tail = VoiceSessionEventTail(capacity=2)
    tail.append(phase_event(1, VoiceSessionPhase.ACTIVE))
    tail.append(phase_event(2, VoiceSessionPhase.RECONNECTING))
    tail.append(phase_event(3, VoiceSessionPhase.ACTIVE))
    snapshot = VoiceSessionSnapshot(
        identity=identity(),
        phase=VoiceSessionPhase.RECONNECTING,
        session_sequence=3,
        journal_sequence=12,
        generation=7,
    )

    result = SemanticResumePlanner(event_tail=tail).plan(
        snapshot=snapshot,
        last_session_sequence=0,
    )

    assert result.snapshot == snapshot
    assert result.events == ()
    assert result.resume_from_sequence == 3


def test_resume_returns_only_the_contiguous_event_delta_when_available() -> None:
    tail = VoiceSessionEventTail(capacity=3)
    tail.append(phase_event(1, VoiceSessionPhase.ACTIVE))
    tail.append(phase_event(2, VoiceSessionPhase.RECONNECTING))
    tail.append(phase_event(3, VoiceSessionPhase.ACTIVE))
    snapshot = VoiceSessionSnapshot(
        identity=identity(),
        phase=VoiceSessionPhase.ACTIVE,
        session_sequence=3,
        journal_sequence=12,
        generation=7,
    )

    result = SemanticResumePlanner(event_tail=tail).plan(
        snapshot=snapshot,
        last_session_sequence=1,
    )

    assert result.snapshot is None
    assert [event.session_sequence for event in result.events] == [2, 3]


def test_snapshot_rejects_schema_versions_before_one() -> None:
    with pytest.raises(ValueError, match="schema version"):
        VoiceSessionSnapshot(
            identity=identity(),
            phase=VoiceSessionPhase.ACTIVE,
            session_sequence=3,
            journal_sequence=12,
            generation=7,
            schema_version=0,
        )
