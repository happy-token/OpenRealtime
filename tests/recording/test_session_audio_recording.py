from __future__ import annotations

import asyncio
import io
import wave
from dataclasses import replace
from datetime import timedelta

import pytest

from server.artifacts import ArtifactAccessScope, InMemoryArtifactStore
from server.conversation_journal import InMemoryConversationJournal, JournalScope, StructuredContent
from server.realtime.protocol import AudioEncoding, AudioFrame
from server.realtime.recording import SessionAudioRecorder, recording_scope
from tests.realtime.test_realtime_websocket_bridge import context


def audio(sequence=0, *, timestamp=0, data=b"\x01\x00" * 160):
    return AudioFrame(
        "stream",
        sequence,
        timestamp,
        len(data) // 2 * 1000000 // 16000,
        AudioEncoding.PCM_S16LE,
        16000,
        1,
        data,
    )


@pytest.mark.asyncio
async def test_dual_tracks_are_verified_artifacts_with_session_manifests():
    store, journal = InMemoryArtifactStore(), InMemoryConversationJournal()
    failures = []
    recorder = SessionAudioRecorder(
        context=context(), artifacts=store, journal=journal, on_failure=failures.append
    )
    recorder.capture("input", audio(), context=context(), epoch="input-1")
    output_context = replace(context(), response_id="response-1")
    recorder.capture(
        "sent",
        audio(data=b"\x02\x00" * 160),
        context=output_context,
        epoch="output-1",
        speech_id="speech-1",
    )
    assert await recorder.close()
    items = await journal.read(recording_scope(context()))
    assert len(items) == 2
    for item, direction in zip(items, ["input", "sent"]):
        manifest = next(part.value for part in item.content if isinstance(part, StructuredContent))
        assert manifest["direction"] == direction
        assert manifest["voice_session_id"] == context().voice_session_id
        assert manifest["playback_confirmation"] == "not-inferred"
        record = await store.get_record(manifest["artifact_id"])
        assert record.request.source_id == context().voice_session_id
        assert record.request.source_kind == "voice_session_recording"
        assert record.request.retention_until - record.created_at >= timedelta(days=6, hours=23)
        assert record.request.classification == "restricted"
        payload = await store.read_for(
            ArtifactAccessScope(context().tenant_id, context().user_id), record.artifact_id
        )
        with wave.open(io.BytesIO(payload), "rb") as wav:
            assert wav.getnframes() == 160
            assert wav.getframerate() == 16000
            assert (
                wav.readframes(160) == (b"\x01\x00" if direction == "input" else b"\x02\x00") * 160
            )
    assert not failures
    assert not await journal.read(JournalScope.from_context(context()))


@pytest.mark.asyncio
async def test_gaps_context_and_epoch_changes_split_instead_of_inventing_audio():
    journal = InMemoryConversationJournal()
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=journal,
        on_failure=lambda reason: None,
    )
    recorder.capture("input", audio(0), context=context(), epoch="a")
    recorder.capture("input", audio(2, timestamp=30000), context=context(), epoch="a")
    recorder.capture(
        "input", audio(0), context=replace(context(), generation=2, turn_id="turn-2"), epoch="b"
    )
    assert await recorder.close()
    items = await journal.read(recording_scope(context()))
    assert len(items) == 3
    manifests = [item.content[0].value for item in items]
    assert [item["start_sample"] for item in manifests] == [0, 480, 0]
    assert [item["sample_count"] for item in manifests] == [160] * 3
    assert manifests[1]["discontinuity"]
    assert items[2].context.generation == 2


@pytest.mark.asyncio
async def test_foreign_session_is_rejected_without_recording_its_audio():
    journal = InMemoryConversationJournal()
    failures = []
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=journal,
        on_failure=failures.append,
    )
    recorder.capture(
        "input", audio(), context=replace(context(), voice_session_id="foreign"), epoch="input"
    )
    assert recorder.failure == "identity_mismatch"
    await recorder.close()
    assert not await journal.read(recording_scope(context()))
    assert failures == ["identity_mismatch"]


@pytest.mark.asyncio
async def test_blocked_storage_is_bounded_and_retains_real_write_owner():
    class Blocked(InMemoryArtifactStore):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def upload(self, artifact_id, data):
            self.entered.set()
            await self.release.wait()
            return await super().upload(artifact_id, data)

    store = Blocked()
    failures = []
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=store,
        journal=InMemoryConversationJournal(),
        on_failure=failures.append,
        segment_bytes=320,
        write_timeout_s=0.02,
    )
    recorder.capture("input", audio(), context=context(), epoch="input")
    await asyncio.wait_for(store.entered.wait(), 1)
    assert not await recorder.close(timeout_s=0.05)
    assert recorder.failure == "storage_timeout"
    assert recorder.pending_writes == 1
    store.release.set()
    await asyncio.wait_for(recorder.wait_settled(), 1)
    assert recorder.pending_writes == 0
    assert failures == ["storage_timeout"]


@pytest.mark.asyncio
async def test_byte_budget_fails_explicitly_without_blocking_capture():
    failures = []
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=InMemoryConversationJournal(),
        on_failure=failures.append,
        max_buffered_bytes=320,
    )
    recorder.capture("input", audio(), context=context(), epoch="input")
    recorder.capture("sent", audio(), context=context(), epoch="output", speech_id="speech")
    assert recorder.failure == "recording_byte_budget"
    await recorder.close()
    assert failures == ["recording_byte_budget"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "finalize"])
async def test_store_must_preserve_original_artifact_identity(operation):
    class ForeignArtifact(InMemoryArtifactStore):
        async def upload(self, artifact_id, data):
            record = await super().upload(artifact_id, data)
            return (
                replace(record, artifact_id="foreign-artifact") if operation == "upload" else record
            )

        async def finalize(self, artifact_id):
            record = await super().finalize(artifact_id)
            return (
                replace(record, artifact_id="foreign-artifact")
                if operation == "finalize"
                else record
            )

    journal = InMemoryConversationJournal()
    recorder = SessionAudioRecorder(
        context=context(), artifacts=ForeignArtifact(), journal=journal, on_failure=lambda _: None
    )
    recorder.capture("input", audio(), context=context(), epoch="input")
    assert not await recorder.close()
    assert recorder.failure == "storage_write_failed"
    assert not await journal.read(recording_scope(context()))


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_observer_errors_cannot_escape_media_capture_or_settlement(error):
    calls = []

    def failed(reason):
        calls.append(reason)
        raise error("observer unavailable")

    def settled():
        calls.append("settled")
        raise error("observer unavailable")

    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=InMemoryConversationJournal(),
        on_failure=failed,
        on_settled=settled,
    )
    recorder.capture(
        "input", audio(), context=replace(context(), voice_session_id="foreign"), epoch="input"
    )
    assert not await recorder.close()
    assert calls == ["identity_mismatch", "settled"]


@pytest.mark.asyncio
async def test_segments_have_hard_five_second_bound():
    journal = InMemoryConversationJournal()
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=journal,
        on_failure=lambda _: None,
    )
    recorder.capture("input", audio(data=b"\0\0" * 79040), context=context(), epoch="input")
    recorder.capture(
        "input", audio(1, timestamp=4940000, data=b"\0\0" * 1600), context=context(), epoch="input"
    )
    assert await recorder.close()
    assert len(await journal.read(recording_scope(context()))) == 2
    assert all(
        item.content[0].value["sample_count"] <= 80000
        for item in await journal.read(recording_scope(context()))
    )
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=journal,
        on_failure=lambda _: None,
    )
    recorder.capture("input", audio(data=b"\0\0" * 112000), context=context(), epoch="input")
    assert recorder.failure == "recording_audio_format"
    assert not await recorder.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [{"stream_id": "s" * 513}, {"sequence": 2**100}, {"timestamp_us": 2**100}, {"sequence": 1.5}],
)
async def test_metadata_budget_rejects_unbounded_or_inexact_frame_identity(changes):
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=InMemoryConversationJournal(),
        on_failure=lambda _: None,
    )
    recorder.capture("input", replace(audio(), **changes), context=context(), epoch="input")
    assert recorder.failure is not None
    assert not await recorder.close()
