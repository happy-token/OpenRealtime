"""Runtime-owned identity, lifecycle, and event models for Voice Sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class VoiceSessionPhase(StrEnum):
    INACTIVE = "inactive"
    STARTING = "starting"
    ACTIVE = "active"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    CLOSED = "closed"


class VoiceSessionFailureCode(StrEnum):
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    CONTEXT_RESTORE_FAILED = "context_restore_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RECOVERY_DEADLINE_EXCEEDED = "recovery_deadline_exceeded"
    INTERNAL_ERROR = "internal_error"


class VoiceSessionDisposition(StrEnum):
    CLOSE = "close"
    CONTINUATION_REQUIRED = "continuation_required"
    KEEP_RECONNECTING = "keep_reconnecting"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionIdentity:
    tenant_id: str
    user_id: str
    device_id: str
    voice_session_id: str
    thread_id: str
    previous_voice_session_id: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.tenant_id,
                self.user_id,
                self.device_id,
                self.voice_session_id,
                self.thread_id,
            )
        ):
            raise ValueError("Voice Session identity fields must be non-empty")
        if self.previous_voice_session_id == "":
            raise ValueError("previous Voice Session identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionPhaseChanged:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    from_phase: VoiceSessionPhase
    to_phase: VoiceSessionPhase
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("Voice Session event identity must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session event sequence and schema version must be positive")
        if self.from_phase is self.to_phase:
            raise ValueError("Voice Session phase transition must change phase")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionReady:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    input_epoch: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.input_epoch:
            raise ValueError("Voice Session ready identity and input epoch must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionClosed:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    reason: str
    degraded_resources: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason:
            raise ValueError("Voice Session close identity and reason must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionRecoveryStarted:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    target_thread_sequence: int
    input_epoch: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.input_epoch:
            raise ValueError("Voice Session Recovery identity must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session Recovery event counters must be positive")
        if self.target_thread_sequence < 0:
            raise ValueError("Voice Session Recovery target must not be negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionRecoveryCompleted:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    target_thread_sequence: int
    projected_through: int
    projection_digest: str
    input_epoch: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all((self.event_id, self.projection_digest, self.input_epoch)):
            raise ValueError("Voice Session Recovery result identity must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session Recovery event counters must be positive")
        if min(self.target_thread_sequence, self.projected_through) < 0:
            raise ValueError("Voice Session Recovery projection counters must not be negative")
        if self.projected_through < self.target_thread_sequence:
            raise ValueError("Voice Session Recovery did not reach its frozen target")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionRecoveryFailed:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    target_thread_sequence: int
    code: VoiceSessionFailureCode
    retryable: bool
    retry_after_ms: int | None
    session_disposition: VoiceSessionDisposition
    safe_message: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.safe_message:
            raise ValueError("Voice Session Recovery failure must be identified")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session Recovery failure event counters must be positive")
        if self.target_thread_sequence < 0:
            raise ValueError("Voice Session Recovery target must not be negative")
        if self.retry_after_ms is not None and self.retry_after_ms < 0:
            raise ValueError("Voice Session retry delay must not be negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionFailed:
    event_id: str
    identity: VoiceSessionIdentity
    session_sequence: int
    occurred_at: datetime
    code: VoiceSessionFailureCode
    phase: VoiceSessionPhase
    retryable: bool
    retry_after_ms: int | None
    session_disposition: VoiceSessionDisposition
    safe_message: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.safe_message:
            raise ValueError("Voice Session failure identity and message must be non-empty")
        if min(self.session_sequence, self.schema_version) < 1:
            raise ValueError("Voice Session event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Voice Session event timestamp must be timezone-aware")
        if self.retry_after_ms is not None and self.retry_after_ms < 0:
            raise ValueError("Voice Session retry delay must not be negative")


VoiceSessionEvent = (
    VoiceSessionClosed
    | VoiceSessionFailed
    | VoiceSessionPhaseChanged
    | VoiceSessionReady
    | VoiceSessionRecoveryCompleted
    | VoiceSessionRecoveryFailed
    | VoiceSessionRecoveryStarted
)
