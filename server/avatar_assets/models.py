"""Domain records for persisted digital-human motion assets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CandidateSourceKind(StrEnum):
    UPLOAD = "upload"
    VIDU = "vidu"
    LIVEPORTRAIT = "liveportrait"
    LTX = "ltx"
    MINIMAX = "minimax"


class MotionBaseCandidatePhase(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    FAILED = "failed"


class AcceptancePhase(StrEnum):
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    FAILED = "failed"


class RenditionPhase(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    FAILED = "failed"


class MotionBasePhase(StrEnum):
    PREPARING = "preparing"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class MediaFacts:
    size_bytes: int
    sha256: str
    duration_ms: int
    width: int
    height: int
    frame_rate_numerator: int
    frame_rate_denominator: int
    video_codec: str
    has_audio: bool
    audio_codec: str | None = None

    def __post_init__(self) -> None:
        if self.size_bytes <= 0 or self.duration_ms <= 0:
            raise ValueError("media size and duration must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("media dimensions must be positive")
        if self.frame_rate_numerator <= 0 or self.frame_rate_denominator <= 0:
            raise ValueError("media frame rate must be positive")
        if not _is_sha256(self.sha256):
            raise ValueError("media sha256 must be a lowercase SHA-256 digest")
        if not self.video_codec:
            raise ValueError("video_codec must be non-empty")
        if self.has_audio != (self.audio_codec is not None):
            raise ValueError("audio_codec presence must match has_audio")


@dataclass(frozen=True, slots=True)
class CandidateCreateRequest:
    tenant_id: str
    owner_id: str
    visual_identity_id: str
    source_kind: CandidateSourceKind
    source_id: str
    artifact_id: str
    logical_name: str
    rights_scope: str
    idempotency_key: str
    media: MediaFacts

    def __post_init__(self) -> None:
        required = (
            self.tenant_id,
            self.owner_id,
            self.visual_identity_id,
            self.source_id,
            self.artifact_id,
            self.logical_name,
            self.rights_scope,
            self.idempotency_key,
        )
        if any(not value for value in required):
            raise ValueError("candidate identity and provenance fields must be non-empty")


@dataclass(frozen=True, slots=True)
class MotionBaseCandidate:
    candidate_id: str
    request: CandidateCreateRequest
    phase: MotionBaseCandidatePhase
    revision: int
    created_at: datetime
    updated_at: datetime
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MotionBaseVideo:
    motion_base_id: str
    tenant_id: str
    owner_id: str
    visual_identity_id: str
    candidate_id: str
    source_master_artifact_id: str
    source_media: MediaFacts
    phase: MotionBasePhase
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LoopWindow:
    start_ms: int
    end_ms: int
    crossfade_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("loop window must have a positive range")
        if self.crossfade_ms < 0:
            raise ValueError("loop crossfade must be non-negative")
        if self.crossfade_ms * 2 > self.end_ms - self.start_ms:
            raise ValueError("loop crossfade cannot exceed half the loop window")


@dataclass(frozen=True, slots=True)
class AcceptanceChecks:
    identity_match: bool
    single_person: bool
    closed_mouth: bool
    fixed_camera: bool
    no_gestures: bool
    rights_confirmed: bool

    @property
    def all_passed(self) -> bool:
        return all(
            (
                self.identity_match,
                self.single_person,
                self.closed_mouth,
                self.fixed_camera,
                self.no_gestures,
                self.rights_confirmed,
            )
        )


@dataclass(frozen=True, slots=True)
class AcceptanceRequest:
    tenant_id: str
    owner_id: str
    candidate_id: str
    reviewer_id: str
    idempotency_key: str
    checks: AcceptanceChecks

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.tenant_id,
                self.owner_id,
                self.candidate_id,
                self.reviewer_id,
                self.idempotency_key,
            )
        ):
            raise ValueError("acceptance identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class AcceptanceRecord:
    acceptance_id: str
    request: AcceptanceRequest
    phase: AcceptancePhase
    revision: int
    created_at: datetime
    updated_at: datetime
    attempt_count: int = 1
    failure_retryable: bool | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    motion_base_id: str | None = None
    source_master_artifact_id: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceClaim:
    record: AcceptanceRecord
    acquired: bool


class WorkInProgress(RuntimeError):
    def __init__(self, work_id: str) -> None:
        super().__init__(f"work is already in progress: {work_id}")
        self.work_id = work_id


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    acceptance_id: str
    motion_base: MotionBaseVideo
    selected: bool = False


@dataclass(frozen=True, slots=True)
class MotionBaseRendition:
    rendition_id: str
    tenant_id: str
    owner_id: str
    motion_base_id: str
    profile: str
    phase: RenditionPhase
    revision: int
    created_at: datetime
    updated_at: datetime
    attempt_count: int = 0
    failure_retryable: bool | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    artifact_id: str | None = None
    media: MediaFacts | None = None
    fit_mode: str = "blur_pad"
    loop: LoopWindow | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MotionBaseSelection:
    tenant_id: str
    owner_id: str
    visual_identity_id: str
    motion_base_id: str
    revision: int
    selected_at: datetime


@dataclass(frozen=True, slots=True)
class RenditionClaim:
    record: MotionBaseRendition
    acquired: bool


class CandidateConflict(RuntimeError):
    pass


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
