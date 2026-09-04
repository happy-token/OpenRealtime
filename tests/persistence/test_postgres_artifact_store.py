from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import replace

import pytest
import pytest_asyncio

from server.artifacts import InMemoryS3ObjectClient
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactConflict,
    ArtifactNotAvailable,
    ArtifactPhase,
    BlobReceipt,
)
from server.persistence.postgres import PostgresArtifactStore, apply_migrations
from tests.artifacts.test_artifact_store import request_for

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest_asyncio.fixture
async def postgres() -> tuple[object, str]:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12)
    schema = f"voiceagent_artifact_test_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    try:
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await pool.close()


@pytest.mark.asyncio
async def test_postgres_metadata_and_object_store_complete_staged_saga(postgres) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    first_process = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        artifact_id_factory=lambda: "artifact-1",
    )
    staging = await first_process.create_staging(request_for())

    with pytest.raises(ArtifactNotAvailable):
        await first_process.read(staging.artifact_id)
    uploaded = await first_process.upload(staging.artifact_id, b"voice-data")
    assert uploaded.phase is ArtifactPhase.STAGING

    recovered_process = PostgresArtifactStore(pool, objects=objects, schema=schema)
    available = await recovered_process.finalize(staging.artifact_id)

    assert available.phase is ArtifactPhase.AVAILABLE
    assert await recovered_process.read(staging.artifact_id) == b"voice-data"
    assert available.receipt is not None
    assert "tenant-1" not in available.receipt.object_key


@pytest.mark.asyncio
async def test_concurrent_artifact_creation_is_strongly_idempotent(postgres) -> None:
    pool, schema = postgres
    store = PostgresArtifactStore(pool, objects=InMemoryS3ObjectClient(), schema=schema)
    request = request_for()

    records = await asyncio.gather(*(store.create_staging(request) for _ in range(30)))

    assert len({record.artifact_id for record in records}) == 1
    with pytest.raises(ArtifactConflict):
        await store.create_staging(replace(request, logical_name="changed.bin"))


@pytest.mark.asyncio
async def test_finalize_missing_object_marks_artifact_failed(postgres) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    record = await store.create_staging(request_for())
    uploaded = await store.upload(record.artifact_id, b"voice-data")
    assert uploaded.receipt is not None
    await objects.delete(uploaded.receipt.object_key)

    failed = await store.finalize(record.artifact_id)

    assert failed.phase is ArtifactPhase.FAILED
    assert failed.failure_reason == "object verification failed"


@pytest.mark.asyncio
async def test_delete_saga_is_retryable_and_honors_retention(postgres) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    record = await store.create_staging(request_for())
    await store.upload(record.artifact_id, b"voice-data")
    await store.finalize(record.artifact_id)

    deleted = await store.delete(record.artifact_id)
    retried = await store.delete(record.artifact_id)

    assert deleted.phase is ArtifactPhase.DELETED
    assert retried == deleted

    retained = await store.create_staging(
        replace(
            request_for(),
            idempotency_key="retained",
            retention_until=deleted.updated_at.replace(year=deleted.updated_at.year + 1),
        )
    )
    with pytest.raises(ArtifactConflict):
        await store.delete(retained.artifact_id)


@pytest.mark.asyncio
async def test_artifact_reads_are_tenant_and_owner_scoped(postgres) -> None:
    pool, schema = postgres
    store = PostgresArtifactStore(
        pool,
        objects=InMemoryS3ObjectClient(),
        schema=schema,
    )
    record = await store.create_staging(request_for())
    await store.upload(record.artifact_id, b"voice-data")
    await store.finalize(record.artifact_id)

    assert (
        await store.read_for(
            ArtifactAccessScope("tenant-1", "user-1"),
            record.artifact_id,
        )
        == b"voice-data"
    )
    with pytest.raises(ArtifactNotAvailable):
        await store.read_for(
            ArtifactAccessScope("tenant-2", "user-1"),
            record.artifact_id,
        )
    with pytest.raises(ArtifactNotAvailable):
        await store.read_for(
            ArtifactAccessScope("tenant-1", "user-2"),
            record.artifact_id,
        )


@pytest.mark.asyncio
async def test_default_mutability_keeps_pre_0011_idempotency_digest_compatible(postgres) -> None:
    pool, schema = postgres
    store = PostgresArtifactStore(
        pool,
        objects=InMemoryS3ObjectClient(),
        schema=schema,
        artifact_id_factory=lambda: "legacy-artifact",
    )
    request = request_for()
    record = await store.create_staging(request)
    legacy_payload = {
        "tenant_id": request.tenant_id,
        "owner_id": request.owner_id,
        "source_kind": request.source_kind,
        "source_id": request.source_id,
        "logical_name": request.logical_name,
        "media_type": request.media_type,
        "classification": request.classification,
        "expected_size": request.expected_size,
        "expected_sha256": request.expected_sha256,
        "retention_until": None,
    }
    legacy_digest = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    async with pool.acquire() as connection:
        await connection.execute(
            f'UPDATE "{schema}".artifacts SET request_digest = $2 WHERE artifact_id = $1',
            record.artifact_id,
            legacy_digest,
        )

    retried = await store.create_staging(request)

    assert retried.artifact_id == record.artifact_id


@pytest.mark.asyncio
async def test_concurrent_postgres_upload_cleans_losing_object(postgres) -> None:
    class BarrierClient(InMemoryS3ObjectClient):
        def __init__(self) -> None:
            super().__init__()
            self._arrivals = 0
            self._both_arrived = asyncio.Event()

        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
            receipt = await super().put(object_key, data, media_type=media_type)
            self._arrivals += 1
            if self._arrivals == 2:
                self._both_arrived.set()
            await self._both_arrived.wait()
            return receipt

        @property
        def object_keys(self) -> set[str]:
            return set(self._objects)

    pool, schema = postgres
    objects = BarrierClient()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    record = await store.create_staging(
        replace(request_for(), expected_size=None, expected_sha256=None)
    )

    outcomes = await asyncio.gather(
        store.upload(record.artifact_id, b"first"),
        store.upload(record.artifact_id, b"second"),
        return_exceptions=True,
    )
    winner = next(outcome for outcome in outcomes if not isinstance(outcome, Exception))

    assert winner.receipt is not None
    assert objects.object_keys == {winner.receipt.object_key}


@pytest.mark.asyncio
async def test_reconciler_cleans_object_after_crash_between_put_and_receipt_cas(postgres) -> None:
    class InspectableObjects(InMemoryS3ObjectClient):
        @property
        def object_keys(self) -> set[str]:
            return set(self._objects)

    class SimulatedCrash(BaseException):
        pass

    def crash_after_put(attempt_id: str) -> None:
        del attempt_id
        raise SimulatedCrash()

    pool, schema = postgres
    objects = InspectableObjects()
    store = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        cleanup_grace_seconds=0,
        after_object_put=crash_after_put,
    )
    record = await store.create_staging(request_for())

    with pytest.raises(SimulatedCrash):
        await store.upload(record.artifact_id, b"voice-data")
    assert len(objects.object_keys) == 1

    reconciled = await store.reconcile_cleanup_ledger()

    assert reconciled["upload_attempts_cleaned"] == 1
    assert objects.object_keys == set()


@pytest.mark.asyncio
async def test_cleanup_fencing_prevents_binding_an_object_claimed_by_reconciler(postgres) -> None:
    class PausedFirstPutClient(InMemoryS3ObjectClient):
        def __init__(self) -> None:
            super().__init__()
            self.stored = asyncio.Event()
            self.release = asyncio.Event()
            self.pause = True

        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
            receipt = await super().put(object_key, data, media_type=media_type)
            if self.pause:
                self.pause = False
                self.stored.set()
                await self.release.wait()
            return receipt

    pool, schema = postgres
    objects = PausedFirstPutClient()
    store = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        cleanup_grace_seconds=0,
    )
    record = await store.create_staging(request_for())
    upload = asyncio.create_task(store.upload(record.artifact_id, b"voice-data"))
    await objects.stored.wait()

    reconciled = await store.reconcile_cleanup_ledger()
    objects.release.set()
    with pytest.raises(ArtifactConflict):
        await upload

    after_fence = await store.get_record(record.artifact_id)
    assert reconciled["upload_attempts_cleaned"] == 1
    assert after_fence is not None
    assert after_fence.phase is ArtifactPhase.STAGING
    assert after_fence.receipt is None

    await store.upload(record.artifact_id, b"voice-data")
    available = await store.finalize(record.artifact_id)
    assert available.phase is ArtifactPhase.AVAILABLE


@pytest.mark.asyncio
async def test_reconciler_retries_failed_cas_loser_delete(postgres) -> None:
    class BarrierDeleteFailureClient(InMemoryS3ObjectClient):
        def __init__(self) -> None:
            super().__init__()
            self._arrivals = 0
            self._both_arrived = asyncio.Event()
            self._delete_failures = 1

        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
            receipt = await super().put(object_key, data, media_type=media_type)
            self._arrivals += 1
            if self._arrivals == 2:
                self._both_arrived.set()
            await self._both_arrived.wait()
            return receipt

        async def delete(self, object_key: str) -> None:
            if self._delete_failures:
                self._delete_failures -= 1
                raise RuntimeError("temporary delete outage")
            await super().delete(object_key)

        @property
        def object_keys(self) -> set[str]:
            return set(self._objects)

    pool, schema = postgres
    objects = BarrierDeleteFailureClient()
    store = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        cleanup_grace_seconds=0,
    )
    record = await store.create_staging(
        replace(request_for(), expected_size=None, expected_sha256=None)
    )
    outcomes = await asyncio.gather(
        store.upload(record.artifact_id, b"first"),
        store.upload(record.artifact_id, b"second"),
        return_exceptions=True,
    )
    winner = next(outcome for outcome in outcomes if not isinstance(outcome, Exception))
    assert winner.receipt is not None
    assert len(objects.object_keys) == 2

    await store.reconcile_cleanup_ledger()

    assert objects.object_keys == {winner.receipt.object_key}


@pytest.mark.asyncio
async def test_reconciler_deletes_unbound_output_but_preserves_pinned_output(postgres) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    store = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        cleanup_grace_seconds=0,
    )
    scope = ArtifactAccessScope("tenant-1", "user-1")

    async def output(idempotency_key: str):
        record = await store.create_staging(
            replace(
                request_for(),
                source_kind="motion_base_rendition",
                source_id=idempotency_key,
                idempotency_key=idempotency_key,
            )
        )
        await store.upload(record.artifact_id, b"voice-data")
        return await store.finalize(record.artifact_id)

    abandoned = await output("abandoned-output")
    retained = await output("retained-output")
    await store.pin_for(scope, retained.artifact_id)

    reconciled = await store.reconcile_cleanup_ledger()

    assert reconciled["artifacts_cleaned"] == 1
    assert (await store.get_record(abandoned.artifact_id)).phase is ArtifactPhase.DELETED
    assert (await store.get_record(retained.artifact_id)).phase is ArtifactPhase.AVAILABLE
