from __future__ import annotations

import asyncio
import os

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.artifacts import InMemoryS3ObjectClient
from server.observability.recordings import RecordingUnavailable
from server.realtime.recording import recording_scope
from server.realtime.registry import SessionHistoryDeletionConflict
from tests.persistence.test_postgres_artifact_store import postgres as postgres  # noqa: PLC0414
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_history_preservation import capture

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


async def runtime_for(schema, objects):
    return await build_application_runtime(
        ApplicationRuntimeConfig(
            state_backend="postgres",
            postgres_schema=schema,
            postgres_dsn=os.getenv(
                "VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp"
            ),
        ),
        object_client_factory=lambda: objects,
    )


@pytest.mark.asyncio
async def test_persistent_preservation_blocks_purge_after_restart_without_objects(postgres):
    _, schema = postgres
    objects = InMemoryS3ObjectClient()
    runtime = await runtime_for(schema, objects)
    try:
        await capture(runtime)
        state = await runtime.preserve_session_recordings(
            context().voice_session_id, actor_id="admin"
        )
        assert state["storage_durable"] and state["preserved_segments"] == 1
    finally:
        await runtime.close()
    rebuilt = await runtime_for(schema, objects)
    try:
        # Metadata/history protection does not depend on S3 availability on restart.
        rebuilt.recordings.artifacts = None
        with pytest.raises(SessionHistoryDeletionConflict):
            await rebuilt.delete_session_history(
                [context().voice_session_id], tenant_id="admin", user_id="admin"
            )
        assert await rebuilt.journal.read(recording_scope(context()))
        assert await rebuilt.diagnostics.session_detail(context().voice_session_id) is not None
    finally:
        await rebuilt.close()


@pytest.mark.asyncio
async def test_postgres_purge_winner_invalidates_source_before_late_mark(postgres, monkeypatch):
    import server.application.runtime as application

    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    runtime, other = await runtime_for(schema, objects), await runtime_for(schema, objects)
    entered, release = asyncio.Event(), asyncio.Event()
    original = application.lock_session_recordings

    async def held_mark_lock(*args, **kwargs):
        if asyncio.current_task().get_name().startswith("recording-operation:"):
            entered.set()
            await release.wait()
        await original(*args, **kwargs)

    monkeypatch.setattr(application, "lock_session_recordings", held_mark_lock)
    await capture(runtime)
    marking = asyncio.create_task(
        runtime.preserve_session_recordings(context().voice_session_id, actor_id="admin")
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (
            await other.delete_session_history(
                [context().voice_session_id], tenant_id="admin", user_id="admin"
            )
        )["deleted_recording_threads"] == 1
        release.set()
        with pytest.raises(RecordingUnavailable) as changed:
            await marking
        assert changed.value.status == 409
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    f'SELECT count(*) FROM "{schema}".session_recording_preservation'
                )
                == 0
            )
            assert (
                await conn.fetchval(f'SELECT bool_or(immutable) FROM "{schema}".artifacts') is False
            )
    finally:
        release.set()
        await asyncio.gather(marking, return_exceptions=True)
        await other.close()
        await runtime.close()


@pytest.mark.asyncio
async def test_postgres_mark_winner_is_seen_after_another_runtime_waits_on_source_lock(
    postgres, monkeypatch
):
    from server.persistence.postgres.recording_preservation import PostgresRecordingPreservation

    _, schema = postgres
    objects = InMemoryS3ObjectClient()
    runtime, other = await runtime_for(schema, objects), await runtime_for(schema, objects)
    marked, release, purge_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = PostgresRecordingPreservation.preserve_session_for

    async def held_mark(self, *args, **kwargs):
        state = await original(self, *args, **kwargs)
        marked.set()
        await release.wait()
        return state

    import server.application.runtime as application

    original_lock = application.lock_session_recordings

    async def observed_lock(*args, **kwargs):
        if not asyncio.current_task().get_name().startswith("recording-operation:"):
            purge_waiting.set()
        await original_lock(*args, **kwargs)

    monkeypatch.setattr(PostgresRecordingPreservation, "preserve_session_for", held_mark)
    monkeypatch.setattr(application, "lock_session_recordings", observed_lock)
    await capture(runtime)
    marking = asyncio.create_task(
        runtime.preserve_session_recordings(context().voice_session_id, actor_id="admin")
    )
    deleting = None
    try:
        await asyncio.wait_for(marked.wait(), 2)
        deleting = asyncio.create_task(
            other.delete_session_history(
                [context().voice_session_id], tenant_id="admin", user_id="admin"
            )
        )
        await asyncio.wait_for(purge_waiting.wait(), 2)
        release.set()
        assert (await marking)["preserved_segments"] == 1
        with pytest.raises(SessionHistoryDeletionConflict):
            await deleting
        assert await runtime.journal.read(recording_scope(context()))
    finally:
        release.set()
        await asyncio.gather(marking, *([deleting] if deleting else []), return_exceptions=True)
        await other.close()
        await runtime.close()
