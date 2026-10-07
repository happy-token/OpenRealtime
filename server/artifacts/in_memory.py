"""Deterministic Artifact Store and S3 object client conformers for tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace

from server.agent_session.driver_protocol import utc_now
from server.artifacts._upload_owner import ArtifactUploadOwner
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactConflict,
    ArtifactCreateRequest,
    ArtifactNotAvailable,
    ArtifactPhase,
    ArtifactRecord,
    ArtifactStore,
    BlobReceipt,
    S3ObjectClient,
    validate_cleanup_limit,
)


class InMemoryS3ObjectClient(S3ObjectClient):
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, BlobReceipt]] = {}

    async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
        del media_type
        digest = hashlib.sha256(data).hexdigest()
        receipt = BlobReceipt(
            object_key=object_key,
            size=len(data),
            sha256=digest,
            etag=digest,
        )
        self._objects[object_key] = (bytes(data), receipt)
        return receipt

    async def head(self, object_key: str) -> BlobReceipt | None:
        value = self._objects.get(object_key)
        return value[1] if value is not None else None

    async def get(self, object_key: str) -> bytes:
        return self._objects[object_key][0]

    async def delete(self, object_key: str) -> None:
        self._objects.pop(object_key, None)


class InMemoryArtifactStore(ArtifactStore):
    """Proves the STAGING→AVAILABLE saga without claiming durability."""

    def __init__(
        self,
        *,
        objects: S3ObjectClient | None = None,
        artifact_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._upload_owner = ArtifactUploadOwner()
        self._objects = objects or InMemoryS3ObjectClient()
        self._artifact_id_factory = artifact_id_factory or (lambda: str(uuid.uuid4()))
        self._records: dict[str, ArtifactRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._request_digests: dict[str, str] = {}
        self._active_uploads: dict[str, int] = {}
        self._pending_upload_cleanup: dict[str, str] = {}
        self._cleanup_attempts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def create_staging(self, request: ArtifactCreateRequest) -> ArtifactRecord:
        key = (request.tenant_id, request.idempotency_key)
        digest = _request_digest(request)
        async with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                if self._request_digests[existing_id] != digest:
                    raise ArtifactConflict(
                        "artifact idempotency_key was reused with different metadata"
                    )
                return self._records[existing_id]
            artifact_id = self._artifact_id_factory()
            if not artifact_id or artifact_id in self._records:
                raise ValueError("artifact_id_factory returned an invalid or duplicate id")
            now = utc_now()
            record = ArtifactRecord(
                artifact_id=artifact_id,
                request=request,
                phase=ArtifactPhase.STAGING,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            self._records[artifact_id] = record
            self._idempotency[key] = artifact_id
            self._request_digests[artifact_id] = digest
            return record

    async def upload(self, artifact_id: str, data: bytes) -> ArtifactRecord:
        return await self._upload_owner.run(lambda: self._upload(artifact_id, data))

    async def _upload(self, artifact_id: str, data: bytes) -> ArtifactRecord:
        record = await self._require(artifact_id)
        digest = hashlib.sha256(data).hexdigest()
        if record.phase is ArtifactPhase.AVAILABLE and record.receipt is not None:
            if record.receipt.size == len(data) and record.receipt.sha256 == digest:
                return record
            raise ArtifactConflict("available artifact has different uploaded content")
        if record.phase is not ArtifactPhase.STAGING:
            raise ArtifactConflict("only STAGING artifacts accept uploads")
        if record.request.expected_size is not None and len(data) != record.request.expected_size:
            raise ArtifactConflict("uploaded artifact size does not match expectation")
        if record.request.expected_sha256 is not None and digest != record.request.expected_sha256:
            raise ArtifactConflict("uploaded artifact digest does not match expectation")
        object_key = _object_key(
            record.request.tenant_id,
            artifact_id,
            digest,
            uuid.uuid4().hex,
        )
        if record.receipt is not None:
            if record.receipt.size != len(data) or record.receipt.sha256 != digest:
                raise ArtifactConflict("artifact already has different uploaded content")
            return record
        async with self._lock:
            current = self._records[artifact_id]
            if current.revision != record.revision or current.phase is not ArtifactPhase.STAGING:
                raise ArtifactConflict("artifact changed before upload")
            self._active_uploads[artifact_id] = self._active_uploads.get(artifact_id, 0) + 1
        try:
            try:
                receipt = await self._objects.put(
                    object_key, data, media_type=record.request.media_type
                )
            except BaseException:
                async with self._lock:
                    self._pending_upload_cleanup[object_key] = artifact_id
                raise
            if (
                receipt.object_key != object_key
                or receipt.size != len(data)
                or receipt.sha256 != digest
            ):
                await self._cleanup_orphan(object_key, artifact_id)
                raise ArtifactConflict("object store returned an invalid upload receipt")
            async with self._lock:
                current = self._records[artifact_id]
                if current.revision == record.revision and current.phase is ArtifactPhase.STAGING:
                    return self._replace(current, receipt=receipt, failure_reason=None)
            await self._cleanup_orphan(object_key, artifact_id)
            if (
                current.phase in {ArtifactPhase.STAGING, ArtifactPhase.AVAILABLE}
                and current.receipt is not None
                and (current.receipt.size == receipt.size and current.receipt.sha256 == digest)
            ):
                return current
            raise ArtifactConflict("artifact changed during upload")
        finally:
            async with self._lock:
                remaining = self._active_uploads[artifact_id] - 1
                if remaining:
                    self._active_uploads[artifact_id] = remaining
                else:
                    del self._active_uploads[artifact_id]

    async def _cleanup_orphan(self, object_key: str, artifact_id: str) -> bool:
        async with self._lock:
            self._pending_upload_cleanup[object_key] = artifact_id
        try:
            await self._objects.delete(object_key)
        except Exception as error:  # noqa: BLE001 - orphan remains owned for retry
            async with self._lock:
                # Retry this orphan after the other pending keys.
                self._pending_upload_cleanup.pop(object_key, None)
                self._pending_upload_cleanup[object_key] = artifact_id
                current = self._records[artifact_id]
                self._replace(current, failure_reason=str(error) or type(error).__name__)
            return False
        async with self._lock:
            self._pending_upload_cleanup.pop(object_key, None)
        return True

    async def finalize(self, artifact_id: str) -> ArtifactRecord:
        record = await self._require(artifact_id)
        if record.phase is ArtifactPhase.AVAILABLE:
            return record
        if record.phase is not ArtifactPhase.STAGING or record.receipt is None:
            raise ArtifactConflict("artifact must be uploaded before finalization")
        observed = await self._objects.head(record.receipt.object_key)
        if (
            observed is None
            or observed.size != record.receipt.size
            or observed.sha256 != record.receipt.sha256
        ):
            async with self._lock:
                current = self._records[artifact_id]
                if (
                    current.revision != record.revision
                    or current.phase is not ArtifactPhase.STAGING
                ):
                    raise ArtifactConflict("artifact changed during finalization")
                return self._replace(
                    current,
                    phase=ArtifactPhase.FAILED,
                    failure_reason="object verification failed",
                )
        async with self._lock:
            current = self._records[artifact_id]
            if current.revision != record.revision:
                raise ArtifactConflict("artifact changed during finalization")
            return self._replace(current, phase=ArtifactPhase.AVAILABLE)

    async def get_record(self, artifact_id: str) -> ArtifactRecord | None:
        async with self._lock:
            return self._records.get(artifact_id)

    async def get_record_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        record = await self.get_record(artifact_id)
        if record is None or (
            record.request.tenant_id,
            record.request.owner_id,
        ) != (scope.tenant_id, scope.owner_id):
            return None
        return record

    async def read(self, artifact_id: str) -> bytes:
        record = await self._require(artifact_id)
        if record.phase is not ArtifactPhase.AVAILABLE or record.receipt is None:
            raise ArtifactNotAvailable(artifact_id)
        data = await self._objects.get(record.receipt.object_key)
        if (
            len(data) != record.receipt.size
            or hashlib.sha256(data).hexdigest() != record.receipt.sha256
        ):
            raise ArtifactNotAvailable(f"artifact integrity check failed: {artifact_id}")
        return data

    async def read_for(self, scope: ArtifactAccessScope, artifact_id: str) -> bytes:
        if await self.get_record_for(scope, artifact_id) is None:
            raise ArtifactNotAvailable(artifact_id)
        return await self.read(artifact_id)

    async def pin_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord:
        async with self._lock:
            current = self._records.get(artifact_id)
            if current is None or (
                current.request.tenant_id,
                current.request.owner_id,
            ) != (scope.tenant_id, scope.owner_id):
                raise ArtifactNotAvailable(artifact_id)
            if current.phase is not ArtifactPhase.AVAILABLE:
                raise ArtifactNotAvailable(artifact_id)
            if current.request.immutable:
                return current
            return self._replace(
                current,
                request=replace(current.request, immutable=True),
            )

    async def delete(self, artifact_id: str) -> ArtifactRecord:
        async with self._lock:
            current = self._records.get(artifact_id)
            if current is None:
                raise KeyError(artifact_id)
            if current.phase is ArtifactPhase.DELETED:
                return current
            if current.request.immutable:
                raise ArtifactConflict("immutable artifact cannot be deleted")
            if (
                current.request.retention_until is not None
                and current.request.retention_until > utc_now()
            ):
                raise ArtifactConflict("artifact retention policy prevents deletion")
            deleting = self._replace(current, phase=ArtifactPhase.DELETING)
            if (
                self._active_uploads.get(artifact_id)
                or artifact_id in self._pending_upload_cleanup.values()
            ):
                raise ArtifactConflict("artifact upload cleanup is still pending")
        if deleting.receipt is not None:
            await self._objects.delete(deleting.receipt.object_key)
        async with self._lock:
            current = self._records[artifact_id]
            if current.phase is ArtifactPhase.DELETED:
                return current
            if current.phase is not ArtifactPhase.DELETING:
                raise ArtifactConflict("artifact changed while completing delete")
            return self._replace(current, phase=ArtifactPhase.DELETED, failure_reason=None)

    async def reconcile_cleanup_ledger(self, *, limit: int = 100) -> dict[str, int]:
        validate_cleanup_limit(limit)
        now = utc_now()
        async with self._lock:
            orphans = [
                (key, artifact_id)
                for key, artifact_id in self._pending_upload_cleanup.items()
                if not self._active_uploads.get(artifact_id)
            ][:limit]
        uploads_cleaned = 0
        for key, artifact_id in orphans:
            if await self._cleanup_orphan(key, artifact_id):
                uploads_cleaned += 1
        async with self._lock:
            candidates = sorted(
                (
                    record
                    for record in self._records.values()
                    if record.request.source_kind == "voice_session_recording"
                    and not record.request.immutable
                    and record.phase is not ArtifactPhase.DELETED
                    and record.request.retention_until is not None
                    and record.request.retention_until <= now
                ),
                key=lambda record: (
                    self._cleanup_attempts.get(record.artifact_id, 0),
                    record.request.retention_until,
                    record.created_at,
                    record.artifact_id,
                ),
            )[:limit]
        cleaned = 0
        for record in candidates:
            async with self._lock:
                self._cleanup_attempts[record.artifact_id] = (
                    self._cleanup_attempts.get(record.artifact_id, 0) + 1
                )
            try:
                await self.delete_for(
                    ArtifactAccessScope(record.request.tenant_id, record.request.owner_id),
                    record.artifact_id,
                )
            except Exception as error:  # noqa: BLE001 - retain failure for maintenance retry
                async with self._lock:
                    current = self._records[record.artifact_id]
                    if current.phase is not ArtifactPhase.DELETED and not current.request.immutable:
                        self._replace(current, failure_reason=str(error) or type(error).__name__)
            else:
                async with self._lock:
                    self._cleanup_attempts.pop(record.artifact_id, None)
                cleaned += 1
        return {"upload_attempts_cleaned": uploads_cleaned, "artifacts_cleaned": cleaned}

    async def delete_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord:
        if await self.get_record_for(scope, artifact_id) is None:
            raise ArtifactNotAvailable(artifact_id)
        return await self.delete(artifact_id)

    async def _require(self, artifact_id: str) -> ArtifactRecord:
        record = await self.get_record(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        return record

    def _replace(self, record: ArtifactRecord, **changes: object) -> ArtifactRecord:
        updated = replace(
            record,
            revision=record.revision + 1,
            updated_at=utc_now(),
            **changes,
        )
        self._records[record.artifact_id] = updated
        return updated


def _object_key(
    tenant_id: str,
    artifact_id: str,
    digest: str,
    upload_attempt_id: str,
) -> str:
    tenant_partition = hashlib.sha256(tenant_id.encode()).hexdigest()[:32]
    return f"artifacts/{tenant_partition}/{artifact_id}/{digest}/{upload_attempt_id}"


def _request_digest(request: ArtifactCreateRequest) -> str:
    payload = {
        "tenant_id": request.tenant_id,
        "owner_id": request.owner_id,
        "source_kind": request.source_kind,
        "source_id": request.source_id,
        "logical_name": request.logical_name,
        "media_type": request.media_type,
        "classification": request.classification,
        "expected_size": request.expected_size,
        "expected_sha256": request.expected_sha256,
        "retention_until": (
            request.retention_until.isoformat() if request.retention_until else None
        ),
    }
    if request.immutable:
        payload["immutable"] = True
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
