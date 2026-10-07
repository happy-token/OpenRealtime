from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime

import pytest

from server.artifacts import InMemoryArtifactStore
from server.conversation_journal import InMemoryConversationJournal
from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.realtime import AudioDelta
from server.realtime.recording import SessionAudioRecorder, recording_scope
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.base import TransportDisconnected
from server.voice_session.protocol import (
    AudioFormat,
    CaptureMode,
    DeviceCaptureProfile,
    InputAudioFrame,
    InputEpochStarted,
)
from tests.realtime.test_realtime_websocket_bridge import (
    RecordingConversation,
    RecordingTransport,
    context,
    event_context,
)
from tests.recording.test_session_audio_recording import audio


def output(sequence=0):
    return AudioDelta(
        event_id=f"audio-{sequence}",
        context=event_context(),
        conversation_sequence=sequence + 1,
        occurred_at=datetime.now(UTC),
        response_id="response-1",
        response_sequence=sequence + 1,
        speech_id="response:response-1",
        frame=audio(sequence),
        segment_index=sequence,
    )


def setup(transport):
    journal = InMemoryConversationJournal()
    recorder = SessionAudioRecorder(
        context=context(),
        artifacts=InMemoryArtifactStore(),
        journal=journal,
        on_failure=lambda _: None,
    )
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(), conversation=conversation, transport=transport, recording=recorder
    )
    return bridge, recorder, journal, conversation


@pytest.mark.asyncio
async def test_bridge_records_valid_input_once_and_actual_output_on_wire_timeline():
    bridge, recorder, journal, conversation = setup(RecordingTransport())
    await bridge.handle_inbound(
        InputEpochStarted(
            input_epoch="input",
            format=AudioFormat(format_id="pcm", sample_rate_hz=16000),
            requested_profile=DeviceCaptureProfile(),
            effective_profile=DeviceCaptureProfile(),
        )
    )
    frame = InputAudioFrame(
        input_epoch="input",
        sequence=0,
        start_sample=0,
        sample_count=160,
        capture_mode=CaptureMode.LIVE,
        pcm16_base64=base64.b64encode(audio().data).decode(),
    )
    await bridge.handle_inbound(frame)
    await bridge.handle_inbound(frame)
    await bridge.handle_event(output(0))
    await bridge.handle_event(output(1))  # Provider timestamp resets, wire clock is contiguous.
    await bridge.close()
    assert recorder.settled
    items = await journal.read(recording_scope(context()))
    assert len(items) == 2
    manifests = [item.content[0].value for item in items]
    assert [(m["direction"], m["sample_count"]) for m in manifests] == [
        ("input", 160),
        ("sent", 320),
    ]
    assert manifests[1]["frames"] == [[1, 0, 160], [2, 160, 160]]
    assert manifests[1]["playback_confirmation"] == "not-inferred"
    assert sum(type(c).__name__ == "AppendAudio" for c in conversation.commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("buffered", [True, False])
async def test_detached_endpoint_never_records_discarded_or_buffered_output(buffered):
    physical = RecordingTransport()
    endpoint = InMemoryEndpointSession(
        "voice-1", physical, physical.receive(), buffer_outbound_frames=buffered
    )
    bridge, recorder, journal, _ = setup(endpoint)
    await endpoint.detach()
    await bridge.handle_event(output())
    await bridge.close()
    assert not await journal.read(recording_scope(context()))
    assert not endpoint._buffer
    assert bridge._playback_by_speech["response:response-1"].audio_samples == 0
    assert recorder.completed_segments == 0


@pytest.mark.asyncio
async def test_failed_physical_send_is_not_a_recorded_output():
    class Failed(RecordingTransport):
        async def send(self, frame):
            raise TransportDisconnected("gone")

    physical = Failed()
    endpoint = InMemoryEndpointSession(
        "voice-1", physical, physical.receive(), buffer_outbound_frames=False
    )
    bridge, _, journal, _ = setup(endpoint)
    await bridge.handle_event(output())
    await bridge.close()
    assert not await journal.read(recording_scope(context()))


@pytest.mark.asyncio
async def test_queued_audio_rechecks_attachment_before_sending():
    physical = RecordingTransport()
    endpoint = InMemoryEndpointSession("voice-1", physical, physical.receive())
    bridge, _, journal, _ = setup(endpoint)
    await endpoint._send_lock.acquire()
    pending = asyncio.create_task(bridge.handle_event(output()))
    await asyncio.sleep(0)
    replacement = RecordingTransport()
    attaching = asyncio.create_task(endpoint.attach(replacement))
    await asyncio.sleep(0)
    endpoint._send_lock.release()
    await asyncio.gather(pending, attaching)
    await bridge.close()
    assert not physical.frames and not replacement.frames
    assert not await journal.read(recording_scope(context()))


@pytest.mark.asyncio
async def test_inflight_physical_send_retains_original_epoch_after_reattachment():
    class Blocked(RecordingTransport):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send(self, frame):
            self.entered.set()
            await self.release.wait()
            await super().send(frame)

    physical = Blocked()
    endpoint = InMemoryEndpointSession("voice-1", physical, physical.receive())
    original_epoch = endpoint.output_epoch
    bridge, _, journal, _ = setup(endpoint)
    pending = asyncio.create_task(bridge.handle_event(output()))
    await physical.entered.wait()
    replacement = RecordingTransport()
    attaching = asyncio.create_task(endpoint.attach(replacement))
    await asyncio.sleep(0)
    physical.release.set()
    await asyncio.gather(pending, attaching)
    await bridge.close()
    items = await journal.read(recording_scope(context()))
    assert len(items) == 1
    assert items[0].content[0].value["epoch"] == original_epoch != endpoint.output_epoch
    assert len(physical.frames) == 1 and not replacement.frames


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_sent_sample_continuity_does_not_invent_gaps_from_wire_sequence(external):
    from server.realtime.protocol.events import SpeechAudioDelta

    transport = RecordingTransport()
    bridge, recorder, journal, _ = setup(transport)
    recorder._max_segments = 1
    for index in range(3):
        source = (
            SpeechAudioDelta(
                event_id=f"speech-{index}",
                context=event_context(),
                conversation_sequence=index + 1,
                occurred_at=datetime.now(UTC),
                speech_id="speech",
                frame=audio(index),
                segment_index=0,
            )
            if external
            else output(index * 2)
        )
        await bridge.handle_event(source)
    await bridge.close()
    assert recorder.failure is None
    items = await journal.read(recording_scope(context()))
    assert len(items) == 1
    assert items[0].content[0].value["sample_count"] == 480
    assert not items[0].content[0].value["discontinuity"]
    assert [f[0] for f in items[0].content[0].value["frames"]] == [
        f.sequence for f in transport.frames
    ]


@pytest.mark.asyncio
async def test_queued_text_is_rechecked_under_physical_send_lock():
    from server.realtime import DisplayContentDelta

    class Versioned(RecordingConversation):
        current = True

        def output_context_current(self, source):
            return self.current

    physical = RecordingTransport()
    endpoint = InMemoryEndpointSession("voice-1", physical, physical.receive())
    bridge, _, journal, _ = setup(endpoint)
    conversation = Versioned()
    bridge._conversation = conversation
    await endpoint._send_lock.acquire()
    task = asyncio.create_task(
        bridge.handle_event(
            DisplayContentDelta(
                event_id="text",
                context=event_context(),
                conversation_sequence=1,
                occurred_at=datetime.now(UTC),
                response_id="response-1",
                response_sequence=1,
                delta="old text",
            )
        )
    )
    await asyncio.sleep(0)
    conversation.current = False
    endpoint._send_lock.release()
    await task
    await bridge.close()
    assert not physical.frames
    assert not await journal.read(recording_scope(context()))
