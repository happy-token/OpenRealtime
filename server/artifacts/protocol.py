"""Artifact metadata lifecycle and S3-compatible blob contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ArtifactPhase(StrEnum):
    STAGING = "staging"
    AVAILABLE = "available"
    QUARANTINED = "quarantined"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ArtifactCreateRequest:
    tenant_id: str
    owner_id: str
    source_kind: str
    source_id: str
    logical_name: str
    media_type: str
    classification: str
    idempotency_key: str
    expected_size: int | None = None
    expected_sha256: str | None = None
    retention_until: datetime | None = None
    immutable: bool = False

    def __post_init__(self) -> None:
        required = (
            self.tenant_id,
            self.owner_id,
            self.source_kind,
            self.source_id,
            self.logical_name,
            self.media_type,
            self.classification,
            self.idempotency_key,
        )
        if any(not value for value in required):
            raise ValueError("Artifact identity and policy fields must be non-empty")
        if self.expected_size is not None and self.expected_size < 0:
            raise ValueError("expected_size must be non-negative")
        if self.expected_sha256 is not None and (
            len(self.expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.expected_sha256)
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
        if self.retention_until is not None and self.retention_until.utcoffset() is None:
            raise ValueError("retention_until must be timezone-aware")
        if self.source_kind == "voice_session_recording" and self.retention_until is None:
            raise ValueError("voice session recording requires a retention deadline")


@dataclass(frozen=True, slots=True)
class ArtifactAccessScope:
    tenant_id: str
    owner_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.owner_id:
            raise ValueError("Artifact access scope must be non-empty")


@dataclass(frozen=True, slots=True)
class BlobReceipt:
    object_key: str
    size: int
    sha256: str
    etag: str | None = None
    version_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    request: ArtifactCreateRequest
    phase: ArtifactPhase
    revision: int
    created_at: datetime
    updated_at: datetime
    receipt: BlobReceipt | None = None
    failure_reason: str | None = None


class ArtifactConflict(RuntimeError):
    pass


class ArtifactNotAvailable(RuntimeError):
    pass


class ArtifactStore(Protocol):
    async def create_staging(self, request: ArtifactCreateRequest) -> ArtifactRecord: ...

    async def upload(self, artifact_id: str, data: bytes) -> ArtifactRecord: ...

    async def finalize(self, artifact_id: str) -> ArtifactRecord: ...

    async def get_record(self, artifact_id: str) -> ArtifactRecord | None: ...

    async def get_record_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord | None: ...

    async def read(self, artifact_id: str) -> bytes: ...

    async def read_for(self, scope: ArtifactAccessScope, artifact_id: str) -> bytes: ...

    async def pin_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord: ...

    async def delete(self, artifact_id: str) -> ArtifactRecord: ...

    async def delete_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord: ...


@runtime_checkable
class ArtifactCleanup(Protocol):
    """Optional maintenance capability, independent of the media request path."""

    async def reconcile_cleanup_ledger(self, *, limit: int = 100) -> dict[str, int]: ...


def validate_cleanup_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("cleanup reconciliation limit must be an integer from 1 to 1000")


class S3ObjectClient(Protocol):
    async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt: ...

    async def head(self, object_key: str) -> BlobReceipt | None: ...

    async def get(self, object_key: str) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...
