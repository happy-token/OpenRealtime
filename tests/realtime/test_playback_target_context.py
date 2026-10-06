"""Playback facts keep the original output context across later input turns."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.realtime import (
    AssistantYieldRequested,
    ReportPlaybackProgress,
    SpeechAudioDelta,
    SpeechPlaybackProgress,
    StartSpeech,
)
from server.realtime.in_memory import InMemoryRealtimeConversation
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.frames import PlaybackProgressFrame
from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
from tests.realtime.test_output_stop_protocol import audio_event
from tests.realtime.test_realtime_websocket_bridge import (
    RecordingConversation,
    RecordingTransport,
    context,
)


def output(direct=False):
    event = audio_event("original-response", 7)
    target = replace(
        event.context,
        turn_id="original-input-identity",
        response_id=None if direct else event.response_id,
    )
    if direct:
        return SpeechAudioDelta(
            event_id="direct-audio",
            context=target,
            conversation_sequence=3,
            occurred_at=datetime.now(UTC),
            speech_id="direct-speech",
            frame=event.frame,
            segment_index=0,
        )
    return replace(event, context=target)


@pytest.mark.parametrize("wire", ["legacy", "v2"])
@pytest.mark.parametrize("phase", ["started", "playing", "stopped", "finished"])
@pytest.mark.parametrize("direct", [False, True])
async def test_playback_projection_uses_original_target_context(wire, phase, direct):
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
        output_epoch="epoch",
    )
    event = output(direct)
    try:
        await bridge.handle_event(event)
        if wire == "v2":
            receipt = PlaybackProgressV2(
                output_epoch="epoch",
                speech_id=event.speech_id,
                generation=7,
                phase=phase,
                played_position_samples=0 if phase == "started" else 1200,
            )
        else:
            receipt = PlaybackProgressFrame(
                generation=7,
                started=phase == "started",
                finished=phase == "finished",
                stopped=phase == "stopped",
                played_audio_end_us=50000 if phase != "started" else None,
            )
        await bridge.handle_inbound(receipt)
        command = conversation.commands[-1]
        assert isinstance(command, ReportPlaybackProgress)
        assert command.context == event.context
        assert command.speech_id == event.speech_id
    finally:
        await bridge.close()


@pytest.mark.parametrize("direct", [False, True])
async def test_precise_stop_projection_cannot_adopt_interrupting_input_context(direct):
    conversation, transport = RecordingConversation(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
        output_epoch="epoch",
        precise_output_stop=True,
    )
    event = output(direct)
    try:
        await bridge.handle_event(event)
        await bridge.handle_event(
            AssistantYieldRequested(
                event_id="yield",
                context=replace(context(), turn_id="interrupting-input", generation=8),
                conversation_sequence=4,
                occurred_at=datetime.now(UTC),
                reason="barge_in_floor_claim",
            )
        )
        request = transport.frames[-1]
        await bridge.handle_inbound(
            OutputStopResult(
                output_epoch=request.output_epoch,
                speech_id=request.speech_id,
                generation=request.generation,
                stop_command_id=request.stop_command_id,
                outcome="queue_stopped",
                played_position_samples=1200,
            )
        )
        assert conversation.commands[-1].stopped
        assert conversation.commands[-1].context == event.context
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
    finally:
        await bridge.close()


async def test_original_context_survives_actual_speech_lifecycle_event_projection():
    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(context=context(), speech_deliveries=deliveries)
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
        output_epoch="epoch",
    )
    event = output(direct=True)
    stream = conversation.events()
    try:
        await conversation.send(
            StartSpeech(
                command_id="start",
                idempotency_key="start",
                context=event.context,
                speech_id=event.speech_id,
            )
        )
        await anext(stream)
        await bridge.handle_event(event)
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id=event.speech_id,
                generation=7,
                phase="started",
                played_position_samples=0,
            )
        )
        progress = await anext(stream)
        assert isinstance(progress, SpeechPlaybackProgress)
        assert progress.context == event.context
        assert progress.started
        record = await deliveries.get(event.speech_id)
        assert record is not None and record.context == progress.context
    finally:
        await bridge.close()
        await conversation.close()
        await stream.aclose()
