from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from server.agent_session.driver_protocol import utc_now
from server.artifacts import ArtifactAccessScope, InMemoryArtifactStore, InMemoryS3ObjectClient
from server.artifacts.protocol import ArtifactConflict, ArtifactPhase
from tests.artifacts.test_artifact_store import request_for
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import recorded


def request(key="one", **changes):
    base = replace(
        request_for(b"hello"),
        source_kind="voice_session_recording",
        source_id="session-1",
        retention_until=utc_now() + timedelta(days=7),
        idempotency_key=key,
    )
    return replace(base, **changes)


@pytest.mark.asyncio
async def test_marked_session_pins_existing_and_future_audio_and_is_scoped_idempotent():
    store = InMemoryArtifactStore()
    scope = ArtifactAccessScope("tenant-1", "user-1")
    first = await store.create_staging(request())
    await store.upload(first.artifact_id, b"hello")
    await store.finalize(first.artifact_id)
    assert await store.get_session_preservation_for(scope, "session-1") is None
    state = await store.preserve_session_for(scope, "session-1", actor_id="admin-1")
    assert state.preserved_segments == 1 and state.pending_segments == 0
    assert (await store.get_record(first.artifact_id)).request.immutable
    replay = await store.preserve_session_for(scope, "session-1", actor_id="admin-2")
    assert replay == state and replay.actor_id == "admin-1"
    second = await store.create_staging(request("two"))
    await store.upload(second.artifact_id, b"hello")
    assert (await store.finalize(second.artifact_id)).request.immutable
    assert (await store.get_session_preservation_for(scope, "session-1")).preserved_segments == 2
    assert (
        await store.get_session_preservation_for(
            ArtifactAccessScope("foreign", "user-1"), "session-1"
        )
        is None
    )
    foreign = await store.create_staging(request("foreign", owner_id="other"))
    await store.upload(foreign.artifact_id, b"hello")
    assert not (await store.finalize(foreign.artifact_id)).request.immutable
    for artifact in (first, second):
        with pytest.raises(ArtifactConflict):
            await store.delete(artifact.artifact_id)


@pytest.mark.asyncio
async def test_preservation_does_not_revive_expired_or_deleting_audio(monkeypatch):
    import server.artifacts.in_memory as memory

    store = InMemoryArtifactStore()
    item = await store.create_staging(request())
    await store.upload(item.artifact_id, b"hello")
    await store.finalize(item.artifact_id)
    monkeypatch.setattr(
        memory, "utc_now", lambda: item.request.retention_until + timedelta(seconds=1)
    )
    state = await store.preserve_session_for(
        ArtifactAccessScope("tenant-1", "user-1"), "session-1", actor_id="admin"
    )
    assert state.preserved_segments == 0 and state.unavailable_segments == 1
    assert not (await store.get_record(item.artifact_id)).request.immutable
    await store.delete(item.artifact_id)
    assert (await store.get_record(item.artifact_id)).phase is ArtifactPhase.DELETED


@pytest.mark.asyncio
async def test_preserve_pending_upload_does_not_change_upload_revision_or_lose_late_bytes(
    monkeypatch,
):
    import server.artifacts.in_memory as memory

    class Blocked(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def put(self, key, data, *, media_type):
            self.entered.set()
            await self.release.wait()
            return await super().put(key, data, media_type=media_type)

    objects = Blocked()
    store = InMemoryArtifactStore(objects=objects)
    staging = await store.create_staging(request())
    uploading = asyncio.create_task(store.upload(staging.artifact_id, b"hello"))
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        state = await store.preserve_session_for(
            ArtifactAccessScope("tenant-1", "user-1"), "session-1", actor_id="admin"
        )
        assert state.pending_segments == 1
        assert (await store.get_record(staging.artifact_id)).revision == staging.revision
        monkeypatch.setattr(
            memory, "utc_now", lambda: staging.request.retention_until + timedelta(seconds=1)
        )
        assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 0
        assert (await store.get_record(staging.artifact_id)).phase is ArtifactPhase.STAGING
        objects.release.set()
        await uploading
        assert (await store.finalize(staging.artifact_id)).request.immutable
    finally:
        objects.release.set()
        await asyncio.gather(uploading, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_collector_accepts_stronger_session_policy_without_weakening_identity():
    from server.conversation_journal import InMemoryConversationJournal

    store = InMemoryArtifactStore()
    ctx = context()
    await store.preserve_session_for(
        ArtifactAccessScope(ctx.tenant_id, ctx.user_id), ctx.voice_session_id, actor_id="admin"
    )
    _, item = await recorded(InMemoryConversationJournal(), store)
    record = await store.get_record(item.content[0].value["artifact_id"])
    assert record.request.immutable and record.phase is ArtifactPhase.AVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [None, "", False, "x" * 257])
async def test_preservation_rejects_invalid_actor_identity(actor):
    with pytest.raises(ValueError):
        await InMemoryArtifactStore().preserve_session_for(
            ArtifactAccessScope("tenant-1", "user-1"), "session-1", actor_id=actor
        )


@pytest.mark.asyncio
async def test_mark_exactly_at_expiry_does_not_revive_available_audio(monkeypatch):
    import server.artifacts.in_memory as memory

    store = InMemoryArtifactStore()
    item = await store.create_staging(request())
    await store.upload(item.artifact_id, b"hello")
    await store.finalize(item.artifact_id)
    monkeypatch.setattr(memory, "utc_now", lambda: item.request.retention_until)
    state = await store.preserve_session_for(
        ArtifactAccessScope("tenant-1", "user-1"), "session-1", actor_id="admin"
    )
    assert state.preserved_segments == 0 and state.unavailable_segments == 1
