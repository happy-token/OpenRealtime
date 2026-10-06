from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from server.realtime import (
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    RecordOutputStop,
    ReportPlaybackProgress,
    ResponseCompleted,
    ResponseStarted,
    SpeechAudioDelta,
)
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.frame_parsing import parse_inbound_frame
from server.transport.frames import AssistantAudioChunkFrame, AssistantSpeechCancelledFrame
from server.voice_session.protocol import OutputStopResult
from tests.realtime.test_realtime_websocket_bridge import (
    RecordingConversation,
    RecordingTransport,
    context,
    event_context,
)


async def test_precise_stop_has_one_stable_operation_per_output_target():
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=RecordingConversation(),
        transport=transport, output_epoch="epoch", precise_output_stop=True)
    now = datetime.now(UTC)
    await bridge.handle_event(ResponseStarted(event_id="start", context=event_context(),
        conversation_sequence=1, occurred_at=now, response_id="response-1", response_sequence=1))
    for index in range(2):
        await bridge.handle_event(AssistantYieldRequested(event_id=f"yield-{index}", context=event_context(),
            conversation_sequence=index + 2, occurred_at=now, reason="barge_in_floor_claim"))
    assert len(transport.frames) == 1
    stop = transport.frames[0]
    assert stop.output_epoch == "epoch" and stop.speech_id == "response:response-1"
    assert stop.stop_command_id
    assert bridge.output_stop_snapshot()[0].state == "STOP_REQUESTED"
    await bridge.close()


def test_stop_wire_identity_and_position_invariants():
    with pytest.raises(ValidationError):
        AssistantSpeechCancelledFrame(generation=1, output_epoch="epoch")
    for outcome, position in (("unknown", 0), ("stale", 1), ("queue_stopped", None)):
        with pytest.raises(ValidationError):
            OutputStopResult(output_epoch="epoch", speech_id="speech", generation=1,
                stop_command_id="stop", outcome=outcome, played_position_samples=position)
    result = OutputStopResult(output_epoch="epoch", speech_id="speech", generation=1,
        stop_command_id="stop", outcome="queue_stopped", played_position_samples=0)
    assert parse_inbound_frame(result.model_dump_json()) == result


def audio_event(response="response-1", generation=1):
    return AudioDelta(event_id=f"audio-{response}", context=replace(event_context(response_id=response), generation=generation),
        conversation_sequence=3, occurred_at=datetime.now(UTC), response_id=response, response_sequence=2,
        speech_id=f"response:{response}", segment_index=0,
        frame=AudioFrame(stream_id="tts", sequence=0, timestamp_us=0, duration_us=100000,
            encoding=AudioEncoding.PCM_S16LE, sample_rate_hz=24000, channels=1, data=b"\0" * 4800))


async def stopped_bridge(timeout=1500):
    conversation, transport = RecordingConversation(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport,
        output_epoch="epoch", precise_output_stop=True, output_stop_timeout_ms=timeout)
    await bridge.handle_event(audio_event())
    await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
        conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
    request = transport.frames[-1]
    result = OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
        generation=request.generation, stop_command_id=request.stop_command_id,
        outcome="queue_stopped", played_position_samples=1200)
    return bridge, conversation, transport, result


@pytest.mark.parametrize("field,value", [("output_epoch", "other"), ("speech_id", "other"),
    ("generation", 99), ("stop_command_id", "other")])
async def test_new_audio_waits_for_matching_stop_receipt(field, value):
    bridge, conversation, transport, result = await stopped_bridge()
    sending = asyncio.create_task(bridge.handle_event(audio_event("next", 2)))
    try:
        await asyncio.sleep(0)
        before = list(transport.frames)
        await bridge.handle_inbound(result.model_copy(update={field: value}))
        assert bridge.output_stop_snapshot()[0].state == "STOP_REQUESTED"
        assert not sending.done() and transport.frames == before
        await bridge.handle_inbound(result)
        await asyncio.wait_for(sending, .1)
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
        assert transport.frames[-1].speech_id == "response:next"
        assert conversation.commands[-1].stopped
        count = len(conversation.commands)
        await bridge.handle_inbound(result)
        assert len(conversation.commands) == count
    finally:
        await bridge.close()
        await asyncio.gather(sending, return_exceptions=True)


async def test_unknown_stop_never_releases_new_audio_or_claims_stopped():
    bridge, conversation, transport, result = await stopped_bridge()
    sending = asyncio.create_task(bridge.handle_event(audio_event("next", 2)))
    await asyncio.sleep(0)
    await bridge.handle_inbound(result.model_copy(update={"outcome": "unknown", "played_position_samples": None}))
    await asyncio.wait_for(sending, .1)
    assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
    assert not any(isinstance(command, ReportPlaybackProgress) for command in conversation.commands)
    assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    await bridge.close()


async def test_late_confirmation_cannot_reopen_a_failed_stop_gate():
    bridge, conversation, transport, result = await stopped_bridge(timeout=10)
    await asyncio.sleep(.05)
    await bridge.handle_inbound(result)
    await bridge.handle_event(audio_event("next", 2))
    assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
    assert not any(isinstance(command, ReportPlaybackProgress) for command in conversation.commands)
    assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    await bridge.close()


async def test_close_settles_pending_stop_and_leaves_no_waiter_or_deadline():
    bridge, _, _, _ = await stopped_bridge()
    sending = asyncio.create_task(bridge.handle_event(audio_event("next", 2)))
    await asyncio.sleep(0)
    await bridge.close()
    await asyncio.wait_for(sending, .1)
    assert bridge.output_stop_snapshot()[0].reason == "session_closed"


async def test_missing_stop_receipt_has_bounded_unknown_failure_exit():
    class ClosingTransport(RecordingTransport):
        closed = False
        async def close(self):
            self.closed = True
    transport = ClosingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=RecordingConversation(),
        transport=transport, output_epoch="epoch", precise_output_stop=True, output_stop_timeout_ms=10)
    now = datetime.now(UTC)
    await bridge.handle_event(ResponseStarted(event_id="start", context=event_context(),
        conversation_sequence=1, occurred_at=now, response_id="response-1", response_sequence=1))
    await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
        conversation_sequence=2, occurred_at=now, reason="barge_in_floor_claim"))
    await asyncio.sleep(.05)
    assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
    assert transport.closed
    assert transport.frames[-1].code == "output_stop_unconfirmed"
    await bridge.close()


@pytest.mark.parametrize("field", ["generation", "played_position_samples"])
@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_stop_receipt_requires_strict_integer_evidence(field, value):
    payload = {"output_epoch": "epoch", "speech_id": "speech", "generation": 1,
               "stop_command_id": "stop", "outcome": "queue_stopped",
               "played_position_samples": 0, field: value}
    with pytest.raises(ValidationError):
        OutputStopResult.model_validate(payload)


@pytest.mark.parametrize("transition", ["detach", "epoch", "close"])
async def test_observed_stop_keeps_fact_but_cannot_release_audio_after_projection_invalidation(transition):
    class SlowProjection(RecordingConversation):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def send(self, command):
            if isinstance(command, RecordOutputStop):
                await super().send(command)
                return
            self.entered.set()
            await self.release.wait()
            await super().send(command)

    conversation, transport = SlowProjection(), RecordingTransport()
    transport.output_epoch = "epoch"
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation,
        transport=transport, precise_output_stop=True)
    await bridge.handle_event(audio_event())
    await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
        conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
    request = transport.frames[-1]
    receipt = OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
        generation=request.generation, stop_command_id=request.stop_command_id,
        outcome="queue_stopped", played_position_samples=1200)
    projecting = asyncio.create_task(bridge.handle_inbound(receipt))
    sending = None
    try:
        await asyncio.wait_for(conversation.entered.wait(), .1)
        sending = asyncio.create_task(bridge.handle_event(audio_event("next", 2)))
        await asyncio.sleep(0)
        if transition == "detach":
            await bridge.handle_detached()
        elif transition == "epoch":
            transport.output_epoch = "next-epoch"
        else:
            await bridge.close()
        conversation.release.set()
        await asyncio.wait_for(projecting, 1)
        await asyncio.wait_for(sending, 1)
        snapshot = bridge.output_stop_snapshot()[0]
        assert snapshot.state == "STOP_CONFIRMED"
        assert snapshot.reason == {"detach": "transport_detached", "epoch": "output_epoch_changed",
                                   "close": "session_closed"}[transition]
        assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    finally:
        conversation.release.set()
        await bridge.close()
        await asyncio.gather(projecting, *( [sending] if sending is not None else [] ),
                             return_exceptions=True)


async def test_close_blocks_later_output_even_without_an_outstanding_stop():
    conversation, transport = RecordingConversation(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport)
    await bridge.close()
    await bridge.handle_event(audio_event())
    assert transport.frames == []


async def test_cancelled_projection_preserves_observed_stop_and_settles_audio_waiter():
    class SlowProjection(RecordingConversation):
        entered = asyncio.Event()
        async def send(self, command):
            if isinstance(command, RecordOutputStop):
                await super().send(command)
                return
            self.entered.set()
            await asyncio.Event().wait()

    conversation, transport = SlowProjection(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport,
        output_epoch="epoch", precise_output_stop=True)
    await bridge.handle_event(audio_event())
    await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
        conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
    request = transport.frames[-1]
    receipt = OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
        generation=request.generation, stop_command_id=request.stop_command_id,
        outcome="queue_stopped", played_position_samples=1200)
    projecting = asyncio.create_task(bridge.handle_inbound(receipt))
    sending = None
    try:
        await asyncio.wait_for(conversation.entered.wait(), .1)
        sending = asyncio.create_task(bridge.handle_event(audio_event("next", 2)))
        await asyncio.sleep(0)
        projecting.cancel()
        await asyncio.gather(projecting, return_exceptions=True)
        await asyncio.wait_for(sending, .1)
        snapshot = bridge.output_stop_snapshot()[0]
        assert snapshot.state == "STOP_CONFIRMED" and snapshot.reason == "playback_projection_cancelled"
        assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    finally:
        await bridge.close()
        await asyncio.gather(projecting, *( [sending] if sending is not None else [] ),
                             return_exceptions=True)


async def test_stop_request_send_has_a_deadline_and_closes_the_gate():
    class SlowStopTransport(RecordingTransport):
        async def send(self, frame):
            if isinstance(frame, AssistantSpeechCancelledFrame):
                await asyncio.Event().wait()
            await super().send(frame)

    transport = SlowStopTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=RecordingConversation(),
        transport=transport, output_epoch="epoch", precise_output_stop=True, output_stop_timeout_ms=10)
    await bridge.handle_event(audio_event())
    try:
        await asyncio.wait_for(bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
            conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim")), .2)
        await bridge.handle_event(audio_event("next", 2))
        assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
        assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    finally:
        await bridge.close()


@pytest.mark.parametrize("direct_speech", [False, True])
async def test_stop_wait_does_not_restore_revoked_reply_delivery_permission(direct_speech):
    class RevocableConversation(RecordingConversation):
        allowed = True

        def output_delivery_allowed(self, event):
            return self.allowed

    conversation, transport = RevocableConversation(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation,
        transport=transport, output_epoch="epoch", precise_output_stop=True)
    await bridge.handle_event(audio_event())
    await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
        conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
    request = transport.frames[-1]
    receipt = OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
        generation=request.generation, stop_command_id=request.stop_command_id,
        outcome="queue_stopped", played_position_samples=1200)
    next_audio = audio_event("next", 2)
    if direct_speech:
        next_audio = SpeechAudioDelta(event_id=next_audio.event_id, context=next_audio.context,
            conversation_sequence=next_audio.conversation_sequence, occurred_at=next_audio.occurred_at,
            speech_id=next_audio.speech_id, frame=next_audio.frame, segment_index=0)
    sending = asyncio.create_task(bridge.handle_event(next_audio))
    try:
        await asyncio.sleep(0)
        assert not sending.done()
        conversation.allowed = False
        await bridge.handle_inbound(receipt)
        await asyncio.wait_for(sending, .1)
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
        assert not any(getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames)
    finally:
        await bridge.close()
        await asyncio.gather(sending, return_exceptions=True)


async def test_closing_during_terminal_send_does_not_start_remaining_response_frames():
    class PausingTerminalTransport(RecordingTransport):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.started = []

        async def send(self, frame):
            self.started.append(frame)
            if isinstance(frame, AssistantAudioChunkFrame) and frame.is_final:
                self.entered.set()
                await self.release.wait()
            await super().send(frame)

    conversation, transport = RecordingConversation(), PausingTerminalTransport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport)
    await bridge.handle_event(audio_event())
    completing = asyncio.create_task(bridge.handle_event(ResponseCompleted(event_id="completed",
        context=event_context(), conversation_sequence=5, occurred_at=datetime.now(UTC),
        response_id="response-1", response_sequence=3)))
    try:
        await asyncio.wait_for(transport.entered.wait(), .1)
        await bridge.close()
        before = len(transport.started)
        transport.release.set()
        await asyncio.wait_for(completing, .1)
        assert len(transport.started) == before
    finally:
        transport.release.set()
        await bridge.close()
        await asyncio.gather(completing, return_exceptions=True)
