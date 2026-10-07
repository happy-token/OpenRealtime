"""Direct speech cancellation must stop queued wire output, not only the provider."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.realtime import (
    AppendSpeechText,
    CancelSpeech,
    CommitSpeech,
    InMemoryRealtimeConversation,
    StartSpeech,
)
from server.realtime.protocol import AudioEncoding, AudioFrame
from server.realtime.protocol.events import (
    SpeechAudioDelta,
    SpeechCancelled,
    SpeechPlaybackProgress,
)
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.frames import AssistantSpeechCancelledFrame
from server.voice_session.protocol import OutputStopResult
from tests.realtime.test_realtime_websocket_bridge import RecordingTransport, context


@pytest.mark.parametrize("precise", [True, False])
@pytest.mark.parametrize("new_input", [True, False])
async def test_direct_speech_cancel_reaches_queued_playback(precise: bool, new_input: bool) -> None:
    ctx = context()
    store = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(context=ctx, speech_deliveries=store)
    events = conversation.events()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=ctx, conversation=conversation,
        transport=transport, output_epoch="direct-speech-epoch", precise_output_stop=precise)
    try:
        for command in (
            StartSpeech(command_id="start", idempotency_key="start", context=ctx, speech_id="direct-speech"),
            AppendSpeechText(command_id="text", idempotency_key="text", context=ctx,
                             speech_id="direct-speech", text_sequence=1, delta="这句话还没有播完。"),
            CommitSpeech(command_id="commit", idempotency_key="commit", context=ctx, speech_id="direct-speech"),
        ):
            await conversation.send(command)
            await bridge.handle_event(await anext(events))
        await bridge.handle_event(SpeechAudioDelta(event_id="audio", context=ctx,
            conversation_sequence=4, occurred_at=datetime.now(UTC), speech_id="direct-speech", segment_index=0,
            frame=AudioFrame("provider", 0, 0, 1_000_000, AudioEncoding.PCM_S16LE, 16000, 1, b"\0\0" * 16000)))
        await conversation.send(CancelSpeech(command_id="cancel", idempotency_key="cancel", context=replace(ctx, generation=2, turn_id="new-input") if new_input else ctx,
            speech_id="direct-speech", reason="cancelled"))
        cancelled = await anext(events)
        assert isinstance(cancelled, SpeechCancelled)
        for dimension in ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id"):
            foreign = replace(cancelled, context=replace(cancelled.context, **{dimension: "foreign"}))
            await bridge.handle_event(foreign)
        await bridge.handle_event(replace(cancelled, speech_id="unknown-speech"))
        assert not any(isinstance(frame, AssistantSpeechCancelledFrame) for frame in transport.frames)
        await bridge.handle_event(cancelled)
        await bridge.handle_event(cancelled)  # Redelivery cannot create another operation.
        stops = [frame for frame in transport.frames if isinstance(frame, AssistantSpeechCancelledFrame)]
        assert len(stops) == 1, "provider cancellation did not reach the already queued client audio"
        assert stops[0].generation == ctx.generation
        assert stops[0].reason == "cancelled"
        if precise:
            assert stops[0].output_epoch == "direct-speech-epoch"
            assert stops[0].speech_id == "direct-speech" and stops[0].stop_command_id
            receipt = OutputStopResult(output_epoch=stops[0].output_epoch, speech_id="direct-speech",
                generation=ctx.generation, stop_command_id=stops[0].stop_command_id,
                outcome="queue_stopped", played_position_samples=8000)
            await bridge.handle_inbound(receipt)
            canonical = await anext(events)
            assert isinstance(canonical, SpeechPlaybackProgress) and canonical.stopped and not canonical.completed
            assert canonical.context == ctx and canonical.played_position_samples == 8000
            fact = await store.get_output_stop(ctx, stops[0].stop_command_id)
            assert fact and fact.state == "STOP_CONFIRMED" and fact.played_position_samples == 8000
        before_late = len(transport.frames)
        await bridge.handle_event(SpeechAudioDelta(event_id="late-audio", context=ctx,
            conversation_sequence=5, occurred_at=datetime.now(UTC), speech_id="direct-speech", segment_index=1,
            frame=AudioFrame("provider", 1, 1_000_000, 100_000, AudioEncoding.PCM_S16LE, 16000, 1, b"\0\0" * 1600)))
        assert len(transport.frames) == before_late
    finally:
        await bridge.close()
        await conversation.close()


@pytest.mark.parametrize("precise", [True, False])
async def test_late_cancel_of_old_speech_cannot_stop_same_generation_replacement(precise: bool) -> None:
    ctx = context()
    conversation = InMemoryRealtimeConversation(context=ctx)
    events = conversation.events()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(context=ctx, conversation=conversation,
        transport=transport, output_epoch="replacement-epoch", precise_output_stop=precise)
    try:
        for identity in ("old", "new"):
            for command in (
                StartSpeech(command_id=f"start-{identity}", idempotency_key=f"start-{identity}", context=ctx, speech_id=identity),
                AppendSpeechText(command_id=f"text-{identity}", idempotency_key=f"text-{identity}", context=ctx,
                                 speech_id=identity, text_sequence=1, delta=identity),
                CommitSpeech(command_id=f"commit-{identity}", idempotency_key=f"commit-{identity}", context=ctx, speech_id=identity),
            ):
                await conversation.send(command)
                await bridge.handle_event(await anext(events))
            await bridge.handle_event(SpeechAudioDelta(event_id=f"audio-{identity}", context=ctx,
                conversation_sequence=7, occurred_at=datetime.now(UTC), speech_id=identity, segment_index=0,
                frame=AudioFrame(identity, 0, 0, 100_000, AudioEncoding.PCM_S16LE, 16000, 1, b"\0\0" * 1600)))
        await conversation.send(CancelSpeech(command_id="cancel-old", idempotency_key="cancel-old", context=ctx,
            speech_id="old", reason="cancelled"))
        await bridge.handle_event(await anext(events))
        stops = [frame for frame in transport.frames if isinstance(frame, AssistantSpeechCancelledFrame)]
        if precise:
            assert len(stops) == 1 and stops[0].speech_id == "old"
            assert stops[0].stop_command_id
            await bridge.handle_inbound(OutputStopResult(output_epoch="replacement-epoch", speech_id="old",
                generation=ctx.generation, stop_command_id=stops[0].stop_command_id,
                outcome="queue_stopped", played_position_samples=800))
            progress = await anext(events)
            assert isinstance(progress, SpeechPlaybackProgress) and progress.speech_id == "old" and progress.stopped
        else:
            assert stops == []
        before = len(transport.frames)
        await bridge.handle_event(SpeechAudioDelta(event_id="new-continued", context=ctx,
            conversation_sequence=8, occurred_at=datetime.now(UTC), speech_id="new", segment_index=1,
            frame=AudioFrame("new", 1, 100_000, 100_000, AudioEncoding.PCM_S16LE, 16000, 1, b"\0\0" * 1600)))
        assert len(transport.frames) == before + 1
        assert transport.frames[-1].speech_id == "new"
    finally:
        await bridge.close()
        await conversation.close()
