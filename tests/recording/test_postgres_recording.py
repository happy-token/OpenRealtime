from __future__ import annotations

import io
import os
import wave

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.artifacts import ArtifactAccessScope, InMemoryS3ObjectClient
from server.artifacts.protocol import ArtifactNotAvailable, ArtifactPhase
from server.realtime.recording import recording_scope
from tests.persistence.test_postgres_artifact_store import (
    postgres as postgres,  # noqa: PLC0414 - re-export fixture for injection
)
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_session_audio_recording import audio

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest.mark.asyncio
async def test_real_postgres_default_runtime_commits_verified_dual_track_manifests(postgres):
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    runtime = await build_application_runtime(
        ApplicationRuntimeConfig(
            state_backend="postgres",
            postgres_dsn=os.getenv(
                "VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp"
            ),
            postgres_schema=schema,
        ),
        object_client_factory=lambda: objects,
    )
    try:
        recorder = runtime.open_recording(context())
        assert recorder is not None
        recorder.capture("input", audio(), context=context(), epoch="input")
        recorder.capture("sent", audio(), context=context(), epoch="output", speech_id="speech")
        assert await recorder.close()
        items = await runtime.journal.read(recording_scope(context()))
        assert len(items) == 2
        store = runtime.recordings.artifacts
        for item in items:
            manifest = item.content[0].value
            assert manifest["storage_durable"] is True
            assert manifest["playback_confirmation"] == "not-inferred"
            record = await store.get_record_for(
                ArtifactAccessScope(context().tenant_id, context().user_id), manifest["artifact_id"]
            )
            assert record.phase is ArtifactPhase.AVAILABLE
            payload = await store.read_for(
                ArtifactAccessScope(context().tenant_id, context().user_id), record.artifact_id
            )
            with wave.open(io.BytesIO(payload), "rb") as wav:
                assert wav.readframes(160) == audio().data
            with pytest.raises(ArtifactNotAvailable):
                await store.read_for(
                    ArtifactAccessScope("foreign", context().user_id), record.artifact_id
                )
            async with pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        f'SELECT put_completed FROM "{schema}".artifact_upload_attempts WHERE artifact_id=$1',
                        record.artifact_id,
                    )
                    is True
                )
                assert (
                    await conn.fetchval(
                        f'SELECT cleanup_after FROM "{schema}".artifact_cleanup_intents WHERE artifact_id=$1',
                        record.artifact_id,
                    )
                    == record.request.retention_until
                )
        await store.pin_for(
            ArtifactAccessScope(context().tenant_id, context().user_id),
            items[1].content[0].value["artifact_id"],
        )
        await runtime.telemetry.flush()
        result = await runtime.delete_session_history(
            [context().voice_session_id], tenant_id=context().tenant_id, user_id=context().user_id
        )
        assert result["deleted_recording_threads"] == 1
        assert not await runtime.journal.read(recording_scope(context()))
        # History purge is not a claim of immediate blob erasure under retention.
        for item in items:
            assert (
                await store.get_record(item.content[0].value["artifact_id"])
            ).phase is ArtifactPhase.AVAILABLE
    finally:
        await runtime.close()
