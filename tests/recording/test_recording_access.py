from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from server.application.recording import RecordingWritesPending
from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.artifacts import ArtifactAccessScope, InMemoryArtifactStore
from server.conversation_journal import StructuredContent
from server.realtime.registry import SessionHistoryDeletionConflict
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import recorded


@pytest.mark.asyncio
async def test_session_audio_access_verifies_metadata_and_returns_only_scoped_reference():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        store, item = await recorded(runtime.journal, runtime.recordings.artifacts)
        page = await runtime.recordings.read_page(context().voice_session_id)
        row = page["items"][0]
        assert row["artifact_id"] == item.content[0].value["artifact_id"]
        assert row["status"] == "available" and row["playback_confirmation"] == "not-inferred"
        assert row["journal_sequence"] == str(item.sequence)
        assert row["duration_ms"] == 10 and row["voice_session_id"] == context().voice_session_id
        assert "tenant_id" not in row and "object_key" not in str(page)
        payload = await runtime.recordings.read_audio(
            context().voice_session_id, row["artifact_id"]
        )
        assert payload == await store.read_for(
            ArtifactAccessScope(context().tenant_id, context().user_id), row["artifact_id"]
        )
        from server.observability.recordings import RecordingUnavailable

        with pytest.raises(RecordingUnavailable) as missing:
            await runtime.recordings.read_audio("other-session", row["artifact_id"])
        assert missing.value.status == 404
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_expired_unpinned_recording_is_not_returned_before_cleanup(monkeypatch):
    import server.observability.recordings as access

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        store, item = await recorded(runtime.journal, runtime.recordings.artifacts)
        artifact = item.content[0].value["artifact_id"]
        now = (await store.get_record(artifact)).request.retention_until + timedelta(seconds=1)
        monkeypatch.setattr(access, "utc_now", lambda: now)
        assert (await runtime.recordings.read_page(context().voice_session_id))["items"][0][
            "status"
        ] == "expired"
        with pytest.raises(access.RecordingUnavailable) as expired:
            await runtime.recordings.read_audio(context().voice_session_id, artifact)
        assert expired.value.status == 410
        await store.pin_for(ArtifactAccessScope(context().tenant_id, context().user_id), artifact)
        assert (await runtime.recordings.read_page(context().voice_session_id))["items"][0][
            "pinned"
        ] is True
        assert await runtime.recordings.read_audio(context().voice_session_id, artifact)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_recording_bytes_remain_owned_after_request_timeout_and_block_purge_close():
    class Blocked(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def read_for(self, scope, artifact_id):
            self.entered.set()
            await self.release.wait()
            return await super().read_for(scope, artifact_id)

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    store = Blocked()
    runtime.recordings.artifacts = store
    _, item = await recorded(runtime.journal, store)
    runtime.recordings._query_timeout_s = 0.02
    from server.observability.recordings import RecordingUnavailable

    try:
        with pytest.raises(RecordingUnavailable) as timeout:
            await runtime.recordings.read_audio(
                context().voice_session_id, item.content[0].value["artifact_id"]
            )
        assert timeout.value.status == 503
        assert len(runtime.recordings._reads) == 1
        with (
            pytest.raises(SessionHistoryDeletionConflict),
            runtime.recordings.deletion_guard(
                [(context().tenant_id, context().user_id, context().voice_session_id)]
            ),
        ):
            pass
        with pytest.raises(RecordingWritesPending):
            await runtime.close()
        store.release.set()
        for _ in range(20):
            await asyncio.sleep(0.001)
            if not runtime.recordings._reads:
                break
        assert not runtime.recordings._reads
    finally:
        store.release.set()
        await runtime.close()


@pytest.mark.asyncio
async def test_malformed_recording_manifest_is_not_accepted_as_available_audio():
    from tests.recording.test_recording_query import draft

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        _, item = await recorded(runtime.journal, runtime.recordings.artifacts)
        manifest = item.content[0].value
        manifest["voice_session_id"] = "foreign"
        await runtime.journal.append(
            replace(draft(item), content=(StructuredContent(manifest), item.content[1]))
        )
        from server.observability.recordings import RecordingUnavailable

        with pytest.raises(RecordingUnavailable):
            await runtime.recordings.read_page(context().voice_session_id)
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expired", "removed"])
async def test_recording_authority_is_rechecked_after_actual_bytes_io(monkeypatch, change):
    import server.observability.recordings as access
    from server.realtime.recording import recording_scope

    class Changed(InMemoryArtifactStore):
        async def read_for(self, scope, artifact_id):
            data = await super().read_for(scope, artifact_id)
            if change == "expired":
                deadline = (await self.get_record(artifact_id)).request.retention_until
                monkeypatch.setattr(access, "utc_now", lambda: deadline + timedelta(seconds=1))
            else:
                await runtime.journal.delete_threads([recording_scope(context())])
            return data

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    runtime.recordings.artifacts = Changed()
    try:
        _, item = await recorded(runtime.journal, runtime.recordings.artifacts)
        with pytest.raises(access.RecordingUnavailable) as unavailable:
            await runtime.recordings.read_audio(
                context().voice_session_id, item.content[0].value["artifact_id"]
            )
        assert unavailable.value.status == (410 if change == "expired" else 404)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_cancelled_callers_keep_eight_actual_reads_owned_until_exit():
    from server.observability.recordings import RecordingUnavailable

    class Blocked(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.all_entered = asyncio.Event()
            self.count = 0

        async def read_for(self, scope, artifact_id):
            self.count += 1
            if self.count == 8:
                self.all_entered.set()
            await self.release.wait()
            return await super().read_for(scope, artifact_id)

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    store = Blocked()
    runtime.recordings.artifacts = store
    callers = []
    try:
        _, item = await recorded(runtime.journal, store)
        artifact = item.content[0].value["artifact_id"]
        callers = [
            asyncio.create_task(runtime.recordings.read_audio(context().voice_session_id, artifact))
            for _ in range(8)
        ]
        await asyncio.wait_for(store.all_entered.wait(), 1)
        for caller in callers:
            caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
        assert len(runtime.recordings._reads) == 8
        with pytest.raises(RecordingUnavailable) as capacity:
            await runtime.recordings.read_audio(context().voice_session_id, artifact)
        assert capacity.value.reason == "recording_query_capacity"
        store.release.set()
        await asyncio.gather(*tuple(runtime.recordings._reads))
        await asyncio.sleep(0)
        assert not runtime.recordings._reads
    finally:
        store.release.set()
        await asyncio.gather(*callers, return_exceptions=True)
        await runtime.close()


@pytest.mark.asyncio
async def test_catalog_uses_four_owned_metadata_workers_and_preserves_sequence_order():
    from tests.recording.test_recording_query import draft

    class BlockedMetadata(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.block = False
            self.release = asyncio.Event()
            self.four_entered = asyncio.Event()
            self.active = 0
            self.peak = 0

        async def get_record_for(self, scope, artifact_id):
            if not self.block:
                return await super().get_record_for(scope, artifact_id)
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 4:
                self.four_entered.set()
            try:
                await self.release.wait()
                return await super().get_record_for(scope, artifact_id)
            finally:
                self.active -= 1

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    store = BlockedMetadata()
    runtime.recordings.artifacts = store
    reading = None
    try:
        _, item = await recorded(runtime.journal, store)
        for n in range(7):
            await runtime.journal.append(replace(draft(item), item_id=f"segment-{n}"))
        store.block = True
        reading = asyncio.create_task(runtime.recordings.read_page(context().voice_session_id))
        await asyncio.wait_for(store.four_entered.wait(), 0.1)
        assert store.peak == 4 and len(runtime.recordings._reads) == 1
        store.release.set()
        page = await reading
        assert [row["journal_sequence"] for row in page["items"]] == [str(n) for n in range(1, 9)]
        assert store.peak == 4
    finally:
        store.release.set()
        if reading:
            await asyncio.gather(reading, return_exceptions=True)
        await runtime.close()
