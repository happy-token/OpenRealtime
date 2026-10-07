from __future__ import annotations

import asyncio

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.artifacts import InMemoryArtifactStore
from server.realtime.recording import recording_scope
from server.realtime.registry import SessionHistoryDeletionConflict
from tests.application.test_runtime import FakePool
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_session_audio_recording import audio


@pytest.mark.asyncio
async def test_default_memory_runtime_records_without_opt_in():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        recorder = runtime.open_recording(context())
        assert recorder is not None
        assert runtime.open_recording(context()) is recorder
        recorder.capture("input", audio(), context=context(), epoch="input")
        assert await recorder.close()
        await runtime.telemetry.flush()
        detail = await runtime.diagnostics.session_detail(context().voice_session_id)
        assert detail.events[0].attributes["storage_durable"] is False
        assert len(await runtime.journal.read(recording_scope(context()))) == 1
        result = await runtime.delete_session_history(
            [context().voice_session_id], tenant_id=context().tenant_id, user_id=context().user_id
        )
        assert result["deleted_recording_threads"] == 1
        assert not await runtime.journal.read(recording_scope(context()))
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_postgres_without_object_storage_reports_not_configured(monkeypatch):
    for name in ["S3_ENDPOINT_URL", "S3_BUCKET", "S3_AK", "S3_SK"]:
        monkeypatch.delenv(name, raising=False)
    pool = FakePool()

    async def create_pool(**_):
        return pool

    runtime = await build_application_runtime(
        ApplicationRuntimeConfig(state_backend="postgres", postgres_dsn="test"),
        postgres_pool_factory=create_pool,
    )
    try:
        assert runtime.recordings.storage_status == "not-configured"
        assert runtime.open_recording(context()) is None
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_actual_recording_write_blocks_purge_and_pool_close_until_settled():
    class Blocked(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def upload(self, artifact_id, data):
            self.entered.set()
            await self.release.wait()
            return await super().upload(artifact_id, data)

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    pool = FakePool()
    runtime._pool = pool
    store = Blocked()
    runtime.recordings.artifacts = store
    recorder = runtime.open_recording(context())
    recorder.capture("input", audio(), context=context(), epoch="input")
    closing = asyncio.create_task(recorder.close(timeout_s=0.02))
    await store.entered.wait()
    assert not await closing
    with pytest.raises(SessionHistoryDeletionConflict):
        await runtime.delete_session_history(
            [context().voice_session_id], tenant_id=context().tenant_id, user_id=context().user_id
        )
    from server.application.recording import RecordingWritesPending

    with pytest.raises(RecordingWritesPending):
        await runtime.close()
    assert not pool.closed
    with pytest.raises(RuntimeError, match="closing"):
        runtime.open_recording(context())
    store.release.set()
    await asyncio.wait_for(recorder.wait_settled(), 1)
    await runtime.close()
    assert pool.closed
    assert len(await runtime.journal.read(recording_scope(context()))) == 1


@pytest.mark.asyncio
async def test_purge_reservation_blocks_opening_new_recorder():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        key = (context().tenant_id, context().user_id, context().voice_session_id)
        with runtime.recordings.deletion_guard([key]), pytest.raises(SessionHistoryDeletionConflict):
            runtime.open_recording(context())
        recorder = runtime.open_recording(context())
        assert recorder is not None
        await recorder.close()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_real_voice_session_factory_records_after_admission_and_closes_segment():
    import base64

    from server.voice_session import VoiceSessionIdentity
    from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
    from server.voice_session.protocol import (
        AudioFormat,
        CaptureMode,
        DeviceCaptureProfile,
        InputAudioFrame,
        InputEpochStarted,
    )
    from tests.voice_session.test_endpoint_bridge import EpochTransport, RecordingRuntimeFactory

    class AudioTransport(EpochTransport):
        async def receive(self):
            profile = DeviceCaptureProfile()
            yield InputEpochStarted(
                input_epoch="input",
                format=AudioFormat(format_id="pcm", sample_rate_hz=16000),
                requested_profile=profile,
                effective_profile=profile,
            )
            yield InputAudioFrame(
                input_epoch="input",
                sequence=0,
                start_sample=0,
                sample_count=160,
                capture_mode=CaptureMode.LIVE,
                pcm16_base64=base64.b64encode(audio().data).decode(),
            )
            self.received.set()
            await self._closed.wait()

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    transport = AudioTransport()
    transport.received = asyncio.Event()
    factory = RecordingRuntimeFactory()
    opened = []

    def recording_factory(ctx):
        assert ctx == context() and factory.conversation is not None
        opened.append(ctx.voice_session_id)
        return runtime.open_recording(ctx)

    identity = VoiceSessionIdentity(
        tenant_id=context().tenant_id,
        user_id=context().user_id,
        device_id=context().device_id,
        voice_session_id=context().voice_session_id,
        thread_id=context().thread_id,
    )
    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=context(),
        profile=object(),
        runtime_factory=factory,
        journal=runtime.journal,
        transport=transport,
        admission=runtime.voice_session_admission,
        active_conversations=runtime.active_realtime_conversations,
        recording_factory=recording_factory,
    )
    task = asyncio.create_task(endpoint.run())
    try:
        await asyncio.wait_for(transport.received.wait(), 2)
        await transport.close()
        await asyncio.wait_for(task, 2)
        items = await runtime.journal.read(recording_scope(context()))
        assert opened == [context().voice_session_id]
        assert len(items) == 1
        assert items[0].content[0].value["direction"] == "input"
        assert items[0].content[0].value["sample_count"] == 160
        assert not runtime.recordings._recorders
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["exception", "owner-closing"])
async def test_recording_factory_failure_releases_actual_voice_session_resources(cause):
    from server.voice_session import VoiceSessionIdentity
    from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
    from tests.voice_session.test_endpoint_bridge import EpochTransport, RecordingRuntimeFactory

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    factory = RecordingRuntimeFactory()
    identity = VoiceSessionIdentity(
        tenant_id=context().tenant_id,
        user_id=context().user_id,
        device_id=context().device_id,
        voice_session_id=context().voice_session_id,
        thread_id=context().thread_id,
    )
    if cause == "owner-closing":
        await runtime.recordings.close()
        recording_factory = runtime.open_recording
    else:

        def recording_factory(_):
            raise RuntimeError("recording factory unavailable")

    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=context(),
        profile=object(),
        runtime_factory=factory,
        journal=runtime.journal,
        transport=EpochTransport(),
        admission=runtime.voice_session_admission,
        active_conversations=runtime.active_realtime_conversations,
        recording_factory=recording_factory,
    )
    try:
        await asyncio.wait_for(endpoint.run(), 2)
        assert factory.conversation.closed
        assert runtime.active_realtime_conversations.resolve(context()) is None
        assert not [
            t
            for t in asyncio.all_tasks()
            if not t.done() and t.get_name().startswith("voice-session-")
        ]
    finally:
        if endpoint._runtime is not None:
            await endpoint._runtime.stop(reason="test_cleanup")
        await runtime.close()


@pytest.mark.asyncio
async def test_cancelled_runtime_close_can_be_retried_without_poisoning_resources():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    pool = FakePool()
    runtime._pool = pool
    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.gather(closing, return_exceptions=True)
    await asyncio.wait_for(runtime.close(), 1)
    assert pool.closed


@pytest.mark.asyncio
async def test_cleanup_keeps_real_owner_after_close_caller_leaves():
    class BlockedCleanup(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.exited = asyncio.Event()

        async def reconcile_cleanup_ledger(self, *, limit=100):
            self.entered.set()
            try:
                await self.release.wait()
                return {"upload_attempts_cleaned": 0, "artifacts_cleaned": 0}
            finally:
                self.exited.set()

    from server.application.recording import RecordingWritesPending

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    pool = FakePool()
    runtime._pool = pool
    store = BlockedCleanup()
    runtime.recordings.artifacts = store
    runtime.recordings._cleanup_interval_s = 0.001
    await asyncio.wait_for(store.entered.wait(), 1)
    cleanup = runtime.recordings._cleanup
    closing = asyncio.create_task(runtime.recordings.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.gather(closing, return_exceptions=True)
    with pytest.raises(RecordingWritesPending):
        await runtime.close()
    assert not pool.closed and not cleanup.cancelled() and not store.exited.is_set()
    store.release.set()
    await asyncio.wait_for(store.exited.wait(), 1)
    await asyncio.sleep(0)
    assert runtime.recordings._cleanup is None
    await runtime.close()
    assert pool.closed
