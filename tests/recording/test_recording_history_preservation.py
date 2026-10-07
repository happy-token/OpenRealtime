from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from server.application.runtime import (
    ApplicationRuntime,
    ApplicationRuntimeConfig,
    build_application_runtime,
)
from server.artifacts import ArtifactAccessScope
from server.artifacts.protocol import ArtifactConflict
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.observability.recordings import RecordingUnavailable
from server.realtime.recording import recording_scope
from server.realtime.registry import SessionHistoryDeletionConflict
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_session_audio_recording import audio


async def capture(runtime, ctx=None):
    ctx = ctx or context()
    recorder = runtime.open_recording(ctx)
    recorder.capture("input", audio(), context=ctx, epoch="input")
    assert await recorder.close()
    await runtime.telemetry.flush()


@pytest.mark.asyncio
async def test_preserved_session_history_cannot_lose_manifest_or_diagnostics():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        await capture(runtime)
        store = runtime.recordings.artifacts
        await store.preserve_session_for(
            ArtifactAccessScope(context().tenant_id, context().user_id),
            context().voice_session_id,
            actor_id="admin",
        )
        before = await runtime.journal.read(recording_scope(context()))
        with pytest.raises(SessionHistoryDeletionConflict):
            await runtime.delete_session_history(
                [context().voice_session_id],
                tenant_id="administrator",
                user_id="administrator",
            )
        assert await runtime.journal.read(recording_scope(context())) == before
        assert await runtime.diagnostics.session_detail(context().voice_session_id) is not None
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_internal_preservation_uses_journal_source_and_preserves_future_segments():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        await runtime.journal.append(
            ConversationItemDraft(
                item_id="user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMMITTED,
                producer="core",
                content=(TextContent("hello"),),
            )
        )
        state = await runtime.preserve_session_recordings(
            context().voice_session_id, actor_id="admin"
        )
        assert state["preserved"] and not state["storage_durable"]
        assert state["preserved_segments"] == state["pending_segments"] == 0
        await capture(runtime)
        replay = await runtime.preserve_session_recordings(
            context().voice_session_id, actor_id="another-admin"
        )
        assert replay["marked_at"] == state["marked_at"] and replay["preserved_segments"] == 1
        item = (await runtime.journal.read(recording_scope(context())))[0]
        record = await runtime.recordings.artifacts.get_record(item.content[0].value["artifact_id"])
        assert record.request.owner_id == context().user_id and record.request.immutable
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_batch_history_delete_is_rejected_before_any_session_is_modified():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    other = replace(context(), voice_session_id="other", thread_id="other")
    try:
        await capture(runtime)
        await capture(runtime, other)
        await runtime.preserve_session_recordings(context().voice_session_id, actor_id="admin")
        with pytest.raises(SessionHistoryDeletionConflict):
            await runtime.delete_session_history(
                ["other", context().voice_session_id], tenant_id="admin", user_id="admin"
            )
        assert await runtime.journal.read(recording_scope(other))
        assert await runtime.diagnostics.session_detail("other") is not None
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_unknown_source_is_not_reconstructed_from_an_admin():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        with pytest.raises(RecordingUnavailable) as missing:
            await runtime.preserve_session_recordings("missing", actor_id="admin")
        assert missing.value.status == 404
        assert not runtime.recordings.artifacts._preserved_sessions
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_failed_mark_is_not_misreported_as_successful_preservation(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        await capture(runtime)

        async def conflict(*args, **kwargs):
            raise ArtifactConflict("original mark failed")

        monkeypatch.setattr(runtime.recordings.artifacts, "preserve_session_for", conflict)
        with pytest.raises(ArtifactConflict, match="original mark failed"):
            await runtime.preserve_session_recordings(context().voice_session_id, actor_id="admin")
        assert not runtime.recordings.artifacts._preserved_sessions
    finally:
        await runtime.close()


def sharing_runtime(runtime):
    # Two actual runtimes coordinate through one volatile Artifact Store and Journal.
    return ApplicationRuntime(
        runtime.persistence,
        runtime.telemetry,
        debug_log=runtime.debug_log,
        artifacts=runtime.recordings.artifacts,
    )


@pytest.mark.asyncio
async def test_memory_purge_winner_prevents_a_late_phantom_preservation(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    other = sharing_runtime(runtime)
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.journal.delete_threads

    async def held_delete(scopes):
        entered.set()
        await release.wait()
        return await original(scopes)

    monkeypatch.setattr(runtime.journal, "delete_threads", held_delete)
    await capture(runtime)
    deleting = asyncio.create_task(
        runtime.delete_session_history(
            [context().voice_session_id], tenant_id="admin", user_id="admin"
        )
    )
    marking = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        marking = asyncio.create_task(
            other.preserve_session_recordings(context().voice_session_id, actor_id="admin")
        )
        async with asyncio.timeout(1):
            while not other.recordings._reads:
                await asyncio.sleep(0)
        release.set()
        await deleting
        with pytest.raises(RecordingUnavailable) as changed:
            await marking
        assert changed.value.status in {404, 409}
        assert not runtime.recordings.artifacts._preserved_sessions
    finally:
        release.set()
        await asyncio.gather(deleting, *([marking] if marking else []), return_exceptions=True)
        await other.recordings.close()
        await runtime.close()


@pytest.mark.asyncio
async def test_memory_mark_winner_blocks_another_runtime_purge_after_timeout(monkeypatch):
    from server.application.recording import RecordingWritesPending

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    other = sharing_runtime(runtime)
    entered, release = asyncio.Event(), asyncio.Event()
    store = runtime.recordings.artifacts
    original = store.preserve_session_for

    async def held_mark(*args, **kwargs):
        state = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return state

    monkeypatch.setattr(store, "preserve_session_for", held_mark)
    runtime.recordings._query_timeout_s = 0.02
    await capture(runtime)
    marking = asyncio.create_task(
        runtime.preserve_session_recordings(context().voice_session_id, actor_id="admin")
    )
    deleting = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RecordingUnavailable) as timeout:
            await marking
        assert timeout.value.reason == "recording_source_timeout" and runtime.recordings._reads
        with pytest.raises(RecordingWritesPending):
            await runtime.recordings.close()
        deleting = asyncio.create_task(
            other.delete_session_history(
                [context().voice_session_id], tenant_id="admin", user_id="admin"
            )
        )
        release.set()
        with pytest.raises(SessionHistoryDeletionConflict):
            await deleting
        assert await runtime.journal.read(recording_scope(context()))
    finally:
        release.set()
        await asyncio.gather(marking, *([deleting] if deleting else []), return_exceptions=True)
        async with asyncio.timeout(1):
            while runtime.recordings._reads:
                await asyncio.sleep(0)
        await other.recordings.close()
        await runtime.close()
