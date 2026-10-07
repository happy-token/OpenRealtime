from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import timedelta

import pytest

from server.artifacts import ArtifactAccessScope, InMemoryS3ObjectClient
from server.artifacts.protocol import ArtifactConflict, ArtifactPhase
from server.persistence.postgres import PostgresArtifactStore, PostgresConversationJournal
from tests.artifacts.test_session_recording_preservation import request
from tests.persistence.test_postgres_artifact_store import (
    postgres as postgres,  # noqa: PLC0414 - re-export fixture for injection
)
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import recorded

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)
SCOPE = ArtifactAccessScope("tenant-1", "user-1")


@pytest.mark.asyncio
async def test_preserved_pending_upload_does_not_starve_other_orphan_cleanup(postgres):
    class FirstPutBlocked(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def put(self, key, data, *, media_type):
            if not self.entered.is_set():
                self.entered.set()
                await self.release.wait()
            return await super().put(key, data, media_type=media_type)

    def crash_second_put(attempt_id):
        if objects.release.is_set():
            return
        raise RuntimeError("crash after orphan put")

    pool, schema = postgres
    objects = FirstPutBlocked()
    store = PostgresArtifactStore(
        pool,
        objects=objects,
        schema=schema,
        cleanup_grace_seconds=0,
        after_object_put=crash_second_put,
    )
    kept = await store.create_staging(request())
    uploading = asyncio.create_task(store.upload(kept.artifact_id, b"hello"))
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        await store.preserve_session_for(SCOPE, "session-1", actor_id="admin")
        orphan = await store.create_staging(replace(request("orphan"), source_id="other-session"))
        with pytest.raises(RuntimeError, match="crash after orphan put"):
            await store.upload(orphan.artifact_id, b"hello")
        async with pool.acquire() as conn:
            orphan_key = await conn.fetchval(
                f'SELECT object_key FROM "{schema}".artifact_upload_attempts WHERE artifact_id=$1',
                orphan.artifact_id,
            )
        assert await objects.head(orphan_key) is not None
        for _ in range(3):
            await store.reconcile_cleanup_ledger(limit=1)
        assert await objects.head(orphan_key) is None
        async with pool.acquire() as conn:
            attempt = await conn.fetchrow(
                f'SELECT phase, put_completed FROM "{schema}".artifact_upload_attempts WHERE artifact_id=$1',
                kept.artifact_id,
            )
            assert attempt["phase"] == "pending" and not attempt["put_completed"]
        assert (await store.get_record(kept.artifact_id)).phase is ArtifactPhase.STAGING
        objects.release.set()
        await uploading
        assert (await store.finalize(kept.artifact_id)).request.immutable
    finally:
        objects.release.set()
        await asyncio.gather(uploading, return_exceptions=True)


@pytest.mark.asyncio
async def test_postgres_preserved_session_survives_store_reconstruction_and_future_segments(
    postgres,
):
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    first = await store.create_staging(request())
    await store.upload(first.artifact_id, b"hello")
    await store.finalize(first.artifact_id)
    state = await store.preserve_session_for(SCOPE, "session-1", actor_id="admin-1")
    rebuilt = PostgresArtifactStore(pool, objects=objects, schema=schema)
    assert await rebuilt.get_session_preservation_for(SCOPE, "session-1") == state
    assert await rebuilt.preserve_session_for(SCOPE, "session-1", actor_id="admin-2") == state
    second = await rebuilt.create_staging(request("two"))
    await rebuilt.upload(second.artifact_id, b"hello")
    assert (await rebuilt.finalize(second.artifact_id)).request.immutable
    assert (await rebuilt.get_session_preservation_for(SCOPE, "session-1")).preserved_segments == 2
    assert (
        await rebuilt.get_session_preservation_for(
            ArtifactAccessScope("foreign", "user-1"), "session-1"
        )
        is None
    )
    for record in (first, second):
        with pytest.raises(ArtifactConflict):
            await rebuilt.delete(record.artifact_id)
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    f'SELECT phase FROM "{schema}".artifact_cleanup_intents WHERE artifact_id=$1',
                    record.artifact_id,
                )
                == "cancelled"
            )


@pytest.mark.asyncio
async def test_postgres_preservation_protects_actual_pending_upload_and_its_cleanup_attempt(
    postgres, monkeypatch
):
    import server.persistence.postgres.artifact_store as storage
    import server.persistence.postgres.recording_preservation as preservation

    class Blocked(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def put(self, key, data, *, media_type):
            self.entered.set()
            await self.release.wait()
            return await super().put(key, data, media_type=media_type)

    pool, schema = postgres
    objects = Blocked()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    staging = await store.create_staging(request())
    uploading = asyncio.create_task(store.upload(staging.artifact_id, b"hello"))
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        state = await store.preserve_session_for(SCOPE, "session-1", actor_id="admin")
        assert (
            state.pending_segments == 1
            and (await store.get_record(staging.artifact_id)).revision == staging.revision
        )
        now = staging.request.retention_until + timedelta(seconds=1)
        monkeypatch.setattr(storage, "utc_now", lambda: now)
        monkeypatch.setattr(preservation, "utc_now", lambda: now)
        result = await store.reconcile_cleanup_ledger()
        assert result == {"upload_attempts_cleaned": 0, "artifacts_cleaned": 0}
        assert (await store.get_record(staging.artifact_id)).phase is ArtifactPhase.STAGING
        objects.release.set()
        await uploading
        assert (await store.finalize(staging.artifact_id)).request.immutable
    finally:
        objects.release.set()
        await asyncio.gather(uploading, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_postgres_collector_commits_preserved_session_manifest(postgres):
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    store = PostgresArtifactStore(pool, objects=objects, schema=schema)
    ctx = context()
    await store.preserve_session_for(
        ArtifactAccessScope(ctx.tenant_id, ctx.user_id), ctx.voice_session_id, actor_id="admin"
    )
    _, item = await recorded(PostgresConversationJournal(pool, schema=schema), store)
    assert (await store.get_record(item.content[0].value["artifact_id"])).request.immutable


@pytest.mark.asyncio
async def test_postgres_exact_expiry_is_not_revived_by_session_mark(postgres, monkeypatch):
    import server.persistence.postgres.recording_preservation as preservation

    pool, schema = postgres
    store = PostgresArtifactStore(pool, objects=InMemoryS3ObjectClient(), schema=schema)
    artifact = await store.create_staging(request())
    await store.upload(artifact.artifact_id, b"hello")
    await store.finalize(artifact.artifact_id)
    monkeypatch.setattr(preservation, "utc_now", lambda: artifact.request.retention_until)
    state = await store.preserve_session_for(SCOPE, "session-1", actor_id="admin")
    assert state.preserved_segments == 0 and state.unavailable_segments == 1
    assert not (await store.get_record(artifact.artifact_id)).request.immutable


@pytest.mark.asyncio
async def test_postgres_failed_finalization_rearms_cancelled_expiry_intent(postgres, monkeypatch):
    import server.persistence.postgres.artifact_store as storage

    class InvalidHead(InMemoryS3ObjectClient):
        async def head(self, key):
            return None

    pool, schema = postgres
    store = PostgresArtifactStore(pool, objects=InvalidHead(), schema=schema)
    await store.preserve_session_for(SCOPE, "session-1", actor_id="admin")
    artifact = await store.create_staging(request())
    await store.upload(artifact.artifact_id, b"hello")
    failed = await store.finalize(artifact.artifact_id)
    assert failed.phase is ArtifactPhase.FAILED and not failed.request.immutable
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                f'SELECT phase FROM "{schema}".artifact_cleanup_intents WHERE artifact_id=$1',
                artifact.artifact_id,
            )
            == "pending"
        )
    monkeypatch.setattr(
        storage, "utc_now", lambda: artifact.request.retention_until + timedelta(seconds=1)
    )
    assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 1
    assert (await store.get_record(artifact.artifact_id)).phase is ArtifactPhase.DELETED
