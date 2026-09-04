"""PostgreSQL metadata plus S3-compatible object Artifact Store."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from server.agent_session.driver_protocol import utc_now
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactConflict,
    ArtifactCreateRequest,
    ArtifactNotAvailable,
    ArtifactPhase,
    ArtifactRecord,
    BlobReceipt,
    S3ObjectClient,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresArtifactStore:
    def __init__(
        self,
        executor: Any,
        *,
        objects: S3ObjectClient,
        schema: str = "voiceagent",
        artifact_id_factory: Callable[[], str] | None = None,
        cleanup_grace_seconds: int = 3600,
        cleanup_lease_seconds: int = 300,
        after_object_put: Callable[[str], None] | None = None,
    ) -> None:
        self._executor = executor
        self._objects = objects
        validated = validate_schema_name(schema)
        self._table = f'"{validated}".artifacts'
        self._upload_attempts = f'"{validated}".artifact_upload_attempts'
        self._cleanup_intents = f'"{validated}".artifact_cleanup_intents'
        self._artifact_id_factory = artifact_id_factory or (lambda: str(uuid.uuid4()))
        if cleanup_grace_seconds < 0:
            raise ValueError("cleanup_grace_seconds must be non-negative")
        if cleanup_lease_seconds <= 0:
            raise ValueError("cleanup_lease_seconds must be positive")
        self._cleanup_grace_seconds = cleanup_grace_seconds
        self._cleanup_lease_seconds = cleanup_lease_seconds
        self._after_object_put = after_object_put

    async def create_staging(self, request: ArtifactCreateRequest) -> ArtifactRecord:
        artifact_id = self._artifact_id_factory()
        if not artifact_id:
            raise ValueError("artifact_id_factory returned an empty artifact_id")
        digest = _request_digest(request)
        now = utc_now()
        async with connection_scope(self._executor) as connection, connection.transaction():
            row = await connection.fetchrow(
                f"""
                    INSERT INTO {self._table} (
                        artifact_id, tenant_id, owner_id, source_kind, source_id,
                        logical_name, media_type, classification, idempotency_key,
                        request_digest, expected_size, expected_sha256,
                        retention_until, immutable, phase, revision, created_at, updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9,
                        $10, $11, $12,
                        $13, $14, 'staging', 1, $15, $15
                    )
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    RETURNING *
                    """,
                artifact_id,
                request.tenant_id,
                request.owner_id,
                request.source_kind,
                request.source_id,
                request.logical_name,
                request.media_type,
                request.classification,
                request.idempotency_key,
                digest,
                request.expected_size,
                request.expected_sha256,
                request.retention_until,
                request.immutable,
                now,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"""
                        SELECT * FROM {self._table}
                        WHERE tenant_id = $1 AND idempotency_key = $2
                        """,
                    request.tenant_id,
                    request.idempotency_key,
                )
                if row is None:
                    raise RuntimeError("artifact idempotency record disappeared")
                if row["request_digest"] != digest:
                    raise ArtifactConflict(
                        "artifact idempotency_key was reused with different metadata"
                    )
            if request.source_kind in {
                "motion_base_source_master",
                "motion_base_rendition",
            }:
                await connection.execute(
                    f"""
                        INSERT INTO {self._cleanup_intents} (
                            artifact_id, tenant_id, owner_id, reason, phase,
                            cleanup_after, created_at, updated_at
                        ) VALUES ($1, $2, $3, $4, 'pending', $5, $6, $6)
                        ON CONFLICT (artifact_id) DO NOTHING
                        """,
                    row["artifact_id"],
                    row["tenant_id"],
                    row["owner_id"],
                    "unbound avatar output",
                    now + timedelta(seconds=self._cleanup_grace_seconds),
                    now,
                )
            return self._record(row)

    async def upload(self, artifact_id: str, data: bytes) -> ArtifactRecord:
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
        attempt_id = str(uuid.uuid4())
        now = utc_now()
        async with connection_scope(self._executor) as connection:
            await connection.execute(
                f"""
                INSERT INTO {self._upload_attempts} (
                    attempt_id, artifact_id, tenant_id, owner_id, object_key,
                    size_bytes, sha256, phase, cleanup_after, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, $9, $9)
                """,
                attempt_id,
                artifact_id,
                record.request.tenant_id,
                record.request.owner_id,
                object_key,
                len(data),
                digest,
                now + timedelta(seconds=self._cleanup_grace_seconds),
                now,
            )
        try:
            receipt = await self._objects.put(
                object_key,
                data,
                media_type=record.request.media_type,
            )
        except Exception as error:
            await self._mark_upload_cleanup(attempt_id, str(error) or type(error).__name__)
            raise
        if self._after_object_put is not None:
            self._after_object_put(attempt_id)
        if (
            receipt.object_key != object_key
            or receipt.size != len(data)
            or receipt.sha256 != digest
        ):
            await self._mark_upload_cleanup(attempt_id, "invalid upload receipt")
            cleaned = await self._cleanup_upload_attempt(attempt_id)
            if not cleaned:
                conflict = ArtifactConflict("object store returned an invalid upload receipt")
                conflict.add_note("upload cleanup remains pending in the durable ledger")
                raise conflict
            raise ArtifactConflict("object store returned an invalid upload receipt")
        async with connection_scope(self._executor) as connection, connection.transaction():
            attempt = await connection.fetchrow(
                f"SELECT phase FROM {self._upload_attempts} WHERE attempt_id = $1 FOR UPDATE",
                attempt_id,
            )
            row = None
            if attempt is not None and attempt["phase"] == "pending":
                row = await connection.fetchrow(
                    f"""
                    UPDATE {self._table}
                    SET object_key = $3, object_size = $4, object_sha256 = $5,
                        object_etag = $6, object_version_id = $7,
                        failure_reason = NULL, revision = revision + 1,
                        updated_at = $8
                    WHERE artifact_id = $1 AND revision = $2 AND phase = 'staging'
                    RETURNING *
                    """,
                    artifact_id,
                    record.revision,
                    receipt.object_key,
                    receipt.size,
                    receipt.sha256,
                    receipt.etag,
                    receipt.version_id,
                    utc_now(),
                )
            if row is not None:
                await connection.execute(
                    f"""
                    UPDATE {self._upload_attempts}
                    SET phase = 'committed', failure_reason = NULL, updated_at = $2
                    WHERE attempt_id = $1 AND phase = 'pending'
                    """,
                    attempt_id,
                    utc_now(),
                )
                return self._record(row)
        current = await self._require(artifact_id)
        await self._mark_upload_cleanup(attempt_id, "lost artifact receipt CAS")
        cleaned = await self._cleanup_upload_attempt(attempt_id)
        if (
            current.phase in {ArtifactPhase.STAGING, ArtifactPhase.AVAILABLE}
            and current.receipt is not None
            and current.receipt.size == receipt.size
            and current.receipt.sha256 == receipt.sha256
        ):
            return current
        if not cleaned:
            conflict = ArtifactConflict("artifact changed during upload")
            conflict.add_note("upload cleanup remains pending in the durable ledger")
            raise conflict
        raise ArtifactConflict("artifact changed during upload")

    async def finalize(self, artifact_id: str) -> ArtifactRecord:
        record = await self._require(artifact_id)
        if record.phase is ArtifactPhase.AVAILABLE:
            return record
        if record.phase is not ArtifactPhase.STAGING or record.receipt is None:
            raise ArtifactConflict("artifact must be uploaded before finalization")
        observed = await self._objects.head(record.receipt.object_key)
        verified = (
            observed is not None
            and observed.size == record.receipt.size
            and observed.sha256 == record.receipt.sha256
        )
        target_phase = ArtifactPhase.AVAILABLE if verified else ArtifactPhase.FAILED
        failure_reason = None if verified else "object verification failed"
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table}
                SET phase = $3, failure_reason = $4,
                    revision = revision + 1, updated_at = $5
                WHERE artifact_id = $1 AND revision = $2 AND phase = 'staging'
                RETURNING *
                """,
                artifact_id,
                record.revision,
                target_phase.value,
                failure_reason,
                utc_now(),
            )
            if row is not None:
                return self._record(row)
        current = await self._require(artifact_id)
        if current.phase is target_phase:
            return current
        raise ArtifactConflict("artifact changed during finalization")

    async def get_record(self, artifact_id: str) -> ArtifactRecord | None:
        if not artifact_id:
            raise ValueError("artifact_id must be non-empty")
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"SELECT * FROM {self._table} WHERE artifact_id = $1",
                artifact_id,
            )
            return self._record(row) if row is not None else None

    async def get_record_for(
        self,
        scope: ArtifactAccessScope,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        if not artifact_id:
            raise ValueError("artifact_id must be non-empty")
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._table}
                WHERE artifact_id = $1 AND tenant_id = $2 AND owner_id = $3
                """,
                artifact_id,
                scope.tenant_id,
                scope.owner_id,
            )
            return self._record(row) if row is not None else None

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
        async with connection_scope(self._executor) as connection, connection.transaction():
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table}
                SET immutable = true, revision = revision + 1, updated_at = $4
                WHERE artifact_id = $1 AND tenant_id = $2 AND owner_id = $3
                  AND phase = 'available' AND immutable = false
                RETURNING *
                """,
                artifact_id,
                scope.tenant_id,
                scope.owner_id,
                utc_now(),
            )
            if row is not None:
                await connection.execute(
                    f"""
                    UPDATE {self._cleanup_intents}
                    SET phase = 'cancelled', failure_reason = NULL, updated_at = $2
                    WHERE artifact_id = $1 AND phase = 'pending'
                    """,
                    artifact_id,
                    utc_now(),
                )
        if row is not None:
            return self._record(row)
        current = await self.get_record_for(scope, artifact_id)
        if (
            current is None
            or current.phase is not ArtifactPhase.AVAILABLE
            or not current.request.immutable
        ):
            raise ArtifactNotAvailable(artifact_id)
        await self._finish_cleanup_intent(artifact_id, "cancelled")
        return current

    async def reconcile_cleanup_ledger(self, *, limit: int = 100) -> dict[str, int]:
        if limit <= 0:
            raise ValueError("cleanup reconciliation limit must be positive")
        now = utc_now()
        async with connection_scope(self._executor) as connection:
            attempt_rows = await connection.fetch(
                f"""
                SELECT attempt_id FROM {self._upload_attempts}
                WHERE phase IN ('pending', 'cleanup_pending', 'cleaning')
                  AND cleanup_after <= $1
                ORDER BY cleanup_after, created_at
                LIMIT $2
                """,
                now,
                limit,
            )
        uploads_cleaned = 0
        for row in attempt_rows:
            if await self._cleanup_upload_attempt(row["attempt_id"]):
                uploads_cleaned += 1

        async with connection_scope(self._executor) as connection:
            intent_rows = await connection.fetch(
                f"""
                SELECT artifact_id, tenant_id, owner_id
                FROM {self._cleanup_intents}
                WHERE phase = 'pending' AND cleanup_after <= $1
                ORDER BY cleanup_after, created_at
                LIMIT $2
                """,
                now,
                limit,
            )
        artifacts_cleaned = 0
        for intent in intent_rows:
            scope = ArtifactAccessScope(intent["tenant_id"], intent["owner_id"])
            record = await self.get_record_for(scope, intent["artifact_id"])
            if record is None or record.phase is ArtifactPhase.DELETED:
                await self._finish_cleanup_intent(intent["artifact_id"], "completed")
                artifacts_cleaned += 1
                continue
            if record.request.immutable:
                await self._finish_cleanup_intent(intent["artifact_id"], "cancelled")
                continue
            try:
                await self.delete_for(scope, intent["artifact_id"])
            except Exception as error:  # noqa: BLE001 - ledger records adapter failures
                async with connection_scope(self._executor) as connection:
                    await connection.execute(
                        f"""
                        UPDATE {self._cleanup_intents}
                        SET failure_reason = $2, attempt_count = attempt_count + 1,
                            updated_at = $3
                        WHERE artifact_id = $1 AND phase = 'pending'
                        """,
                        intent["artifact_id"],
                        str(error) or type(error).__name__,
                        utc_now(),
                    )
            else:
                await self._finish_cleanup_intent(intent["artifact_id"], "completed")
                artifacts_cleaned += 1
        return {
            "upload_attempts_cleaned": uploads_cleaned,
            "artifacts_cleaned": artifacts_cleaned,
        }

    async def _mark_upload_cleanup(self, attempt_id: str, reason: str) -> None:
        async with connection_scope(self._executor) as connection:
            await connection.execute(
                f"""
                UPDATE {self._upload_attempts}
                SET phase = 'cleanup_pending', failure_reason = $2,
                    cleanup_after = $3, updated_at = $3
                WHERE attempt_id = $1 AND phase = 'pending'
                """,
                attempt_id,
                reason,
                utc_now(),
            )

    async def _cleanup_upload_attempt(self, attempt_id: str) -> bool:
        cleanup_token = str(uuid.uuid4())
        async with connection_scope(self._executor) as connection, connection.transaction():
            attempt = await connection.fetchrow(
                f"""
                UPDATE {self._upload_attempts}
                SET phase = 'cleaning', cleanup_token = $2,
                    cleanup_after = $4, updated_at = $3
                WHERE attempt_id = $1
                  AND phase IN ('pending', 'cleanup_pending', 'cleaning')
                  AND cleanup_after <= $3
                RETURNING *
                """,
                attempt_id,
                cleanup_token,
                utc_now(),
                utc_now() + timedelta(seconds=self._cleanup_lease_seconds),
            )
            if attempt is None:
                phase = await connection.fetchval(
                    f"SELECT phase FROM {self._upload_attempts} WHERE attempt_id = $1",
                    attempt_id,
                )
                return phase in {"committed", "cleaned"}
        try:
            await self._objects.delete(attempt["object_key"])
        except Exception as error:  # noqa: BLE001 - cleanup must remain retryable
            async with connection_scope(self._executor) as connection:
                await connection.execute(
                    f"""
                    UPDATE {self._upload_attempts}
                    SET phase = 'cleanup_pending', cleanup_token = NULL,
                        failure_reason = $2, cleanup_after = $3, updated_at = $3
                    WHERE attempt_id = $1 AND phase = 'cleaning' AND cleanup_token = $4
                    """,
                    attempt_id,
                    str(error) or type(error).__name__,
                    utc_now() + timedelta(seconds=self._cleanup_grace_seconds),
                    cleanup_token,
                )
            return False
        async with connection_scope(self._executor) as connection:
            await connection.execute(
                f"""
                UPDATE {self._upload_attempts}
                SET phase = 'cleaned', cleanup_token = NULL,
                    failure_reason = NULL, updated_at = $2
                WHERE attempt_id = $1 AND phase = 'cleaning' AND cleanup_token = $3
                """,
                attempt_id,
                utc_now(),
                cleanup_token,
            )
        return True

    async def _finish_cleanup_intent(self, artifact_id: str, phase: str) -> None:
        async with connection_scope(self._executor) as connection:
            await connection.execute(
                f"""
                UPDATE {self._cleanup_intents}
                SET phase = $2, failure_reason = NULL, updated_at = $3
                WHERE artifact_id = $1 AND phase = 'pending'
                """,
                artifact_id,
                phase,
                utc_now(),
            )

    async def delete(self, artifact_id: str) -> ArtifactRecord:
        record = await self._require(artifact_id)
        if record.phase is ArtifactPhase.DELETED:
            return record
        if record.request.immutable:
            raise ArtifactConflict("immutable artifact cannot be deleted")
        if (
            record.request.retention_until is not None
            and record.request.retention_until > utc_now()
        ):
            raise ArtifactConflict("artifact retention policy prevents deletion")
        if record.phase is not ArtifactPhase.DELETING:
            async with connection_scope(self._executor) as connection:
                row = await connection.fetchrow(
                    f"""
                    UPDATE {self._table}
                    SET phase = 'deleting', revision = revision + 1, updated_at = $3
                    WHERE artifact_id = $1 AND revision = $2
                      AND phase NOT IN ('deleted', 'deleting')
                    RETURNING *
                    """,
                    artifact_id,
                    record.revision,
                    utc_now(),
                )
            if row is None:
                record = await self._require(artifact_id)
                if record.phase is ArtifactPhase.DELETED:
                    return record
                if record.phase is not ArtifactPhase.DELETING:
                    raise ArtifactConflict("artifact changed during delete")
            else:
                record = self._record(row)
        if record.receipt is not None:
            await self._objects.delete(record.receipt.object_key)
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table}
                SET phase = 'deleted', revision = revision + 1, updated_at = $3
                WHERE artifact_id = $1 AND revision = $2 AND phase = 'deleting'
                RETURNING *
                """,
                artifact_id,
                record.revision,
                utc_now(),
            )
        if row is not None:
            return self._record(row)
        current = await self._require(artifact_id)
        if current.phase is ArtifactPhase.DELETED:
            return current
        raise ArtifactConflict("artifact changed while completing delete")

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

    @staticmethod
    def _record(row: Mapping[str, Any]) -> ArtifactRecord:
        receipt = None
        if row["object_key"] is not None:
            receipt = BlobReceipt(
                object_key=row["object_key"],
                size=row["object_size"],
                sha256=row["object_sha256"],
                etag=row["object_etag"],
                version_id=row["object_version_id"],
            )
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            request=ArtifactCreateRequest(
                tenant_id=row["tenant_id"],
                owner_id=row["owner_id"],
                source_kind=row["source_kind"],
                source_id=row["source_id"],
                logical_name=row["logical_name"],
                media_type=row["media_type"],
                classification=row["classification"],
                idempotency_key=row["idempotency_key"],
                expected_size=row["expected_size"],
                expected_sha256=row["expected_sha256"],
                retention_until=row["retention_until"],
                immutable=row["immutable"],
            ),
            phase=ArtifactPhase(row["phase"]),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            receipt=receipt,
            failure_reason=row["failure_reason"],
        )


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
