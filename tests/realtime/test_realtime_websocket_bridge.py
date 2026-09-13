from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import UTC, datetime

from server.conversation_journal.models import item_from_draft
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendAudio,
    AppendItem,
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CancelResponse,
    ConfirmationRequested,
    DisplayContentDelta,
    InputTranscriptDelta,
    ItemProjected,
    PlaybackPrecision,
    ReportPlaybackProgress,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpokenContentDelta,
)
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.tools.policy_gateway import ConfirmationChannel
from server.transport.frames import (
    AssistantAudioChunkFrame,
    AssistantResponseCompletedFrame,
    AssistantSpeechCancelledFrame,
    AssistantSpeechTextFrame,
    AssistantTextFrame,
    CancelAssistantResponseFrame,
    ConfirmationDecisionFrame,
    ConfirmationRequestedFrame,
    PlaybackProgressFrame,
    UserTextFrame,
    UserTranscriptFrame,
    VoiceSessionReadyFrame,
)
from server.voice_session.protocol import (
    AudioFormat,
    CaptureMode,
    DeviceCaptureProfile,
    InputAudioAck,
    InputAudioFrame,
    InputEpochStarted,
    PlaybackProgressV2,
)


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="browser",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


class RecordingConversation:
    def __init__(self) -> None:
        self.commands = []

    async def send(self, command) -> None:
        self.commands.append(command)

    async def events(self):
        if False:
            yield

    async def close(self) -> None:
        return None


class RecordingTransport:
    def __init__(self) -> None:
        self.frames = []

    async def receive(self):
        if False:
            yield

    async def send(self, frame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        return None


def event_context(*, response_id: str = "response-1") -> InteractionContext:
    return replace(context(), response_id=response_id)


async def test_bound_confirmation_is_exposed_with_exact_action_identity() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )
    expires_at = datetime.now(UTC)

    await bridge.handle_event(
        ConfirmationRequested(
            event_id="confirmation-event-1",
            context=replace(
                event_context(),
                call_id="call-1",
                confirmation_id="confirmation-1",
            ),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            confirmation_id="confirmation-1",
            action_digest="a" * 64,
            summary="向外部发送消息",
            required_channel=ConfirmationChannel.VOICE,
            expires_at=expires_at,
        )
    )

    assert transport.frames == [
        ConfirmationRequestedFrame(
            confirmation_id="confirmation-1",
            action_digest="a" * 64,
            summary="向外部发送消息",
            required_channel="voice",
            expires_at=expires_at,
            generation=1,
        )
    ]


async def test_bound_confirmation_decision_uses_explicit_control_callback() -> None:
    decisions = []

    async def handle_decision(frame: ConfirmationDecisionFrame) -> None:
        decisions.append(frame)

    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=RecordingTransport(),
        confirmation_decision_handler=handle_decision,
    )
    frame = ConfirmationDecisionFrame(
        confirmation_id="confirmation-1",
        action_digest="a" * 64,
        approved=True,
    )

    await bridge.handle_inbound(frame)

    assert decisions == [frame]


async def test_v2_input_frame_is_validated_mapped_and_acknowledged() -> None:
    conversation = RecordingConversation()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
    )
    await bridge.handle_inbound(
        InputEpochStarted(
            input_epoch="input-1",
            format=AudioFormat(format_id="pcm16-16k-mono"),
            requested_profile=DeviceCaptureProfile(),
            effective_profile=DeviceCaptureProfile(),
        )
    )
    pcm = bytes(1_024)

    await bridge.handle_inbound(
        InputAudioFrame(
            input_epoch="input-1",
            sequence=0,
            start_sample=0,
            sample_count=512,
            capture_mode=CaptureMode.LIVE,
            pcm16_base64=base64.b64encode(pcm).decode("ascii"),
        )
    )

    command = conversation.commands[0]
    assert isinstance(command, AppendAudio)
    assert command.frame.stream_id == "browser:voice-1:input-1"
    assert command.frame.timestamp_us == 0
    assert command.frame.duration_us == 32_000
    assert transport.frames == [
        VoiceSessionReadyFrame(session_sequence=1, input_epoch="input-1"),
        InputAudioAck(
            input_epoch="input-1",
            highest_contiguous_sequence=0,
            next_start_sample=512,
        )
    ]


async def test_floor_claim_stops_browser_playback_before_response_cleanup_finishes() -> None:
    conversation = RecordingConversation()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
    )
    now = datetime.now(UTC)
    await bridge.handle_event(
        ResponseStarted(
            event_id="started-1",
            context=event_context(),
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
        )
    )

    await bridge.handle_event(
        AssistantYieldRequested(
            event_id="yield-1",
            context=replace(context(), turn_id="turn-2", generation=2),
            conversation_sequence=2,
            occurred_at=now,
            reason="barge_in_floor_claim",
        )
    )

    assert transport.frames == [AssistantSpeechCancelledFrame(generation=1)]

    await bridge.handle_event(
        ResponseCancelled(
            event_id="cancelled-1",
            context=replace(event_context(), turn_id="turn-2", generation=2),
            conversation_sequence=3,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            reason="barge_in_floor_claim",
        )
    )
    assert transport.frames == [AssistantSpeechCancelledFrame(generation=1)]


async def test_floor_claim_after_response_completion_cancels_unsettled_playback() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        ResponseStarted(
            event_id="started-1",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
        )
    )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio-1",
            context=response_context,
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=100_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )
    await bridge.handle_event(
        ResponseCompleted(
            event_id="completed-1",
            context=response_context,
            conversation_sequence=3,
            occurred_at=now,
            response_id="response-1",
            response_sequence=3,
        )
    )
    transport.frames.clear()

    await bridge.handle_event(
        AssistantYieldRequested(
            event_id="yield-2",
            context=replace(context(), turn_id="turn-2", generation=2),
            conversation_sequence=4,
            occurred_at=now,
            reason="barge_in_floor_claim",
        )
    )

    assert transport.frames == [AssistantSpeechCancelledFrame(generation=1)]


async def test_response_events_keep_cumulative_text_and_stream_audio_frames() -> None:
    conversation = RecordingConversation()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        ResponseStarted(
            event_id="started",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
        )
    )
    for sequence, delta in enumerate(("你好，", "世界"), start=2):
        await bridge.handle_event(
            DisplayContentDelta(
                event_id=f"display-{sequence}",
                context=response_context,
                conversation_sequence=sequence,
                occurred_at=now,
                response_id="response-1",
                response_sequence=sequence,
                delta=delta,
            )
        )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio",
            context=response_context,
            conversation_sequence=4,
            occurred_at=now,
            response_id="response-1",
            response_sequence=4,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=100_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )
    await bridge.handle_event(
        ResponseCompleted(
            event_id="completed",
            context=response_context,
            conversation_sequence=5,
            occurred_at=now,
            response_id="response-1",
            response_sequence=5,
        )
    )

    assert [frame.text for frame in transport.frames[:2]] == ["你好，", "你好，世界"]
    assert isinstance(transport.frames[0], AssistantTextFrame)
    assert isinstance(transport.frames[2], AssistantAudioChunkFrame)
    terminal_audio = transport.frames[3]
    assert isinstance(terminal_audio, AssistantAudioChunkFrame)
    assert terminal_audio.pcm16_base64 == ""
    assert terminal_audio.sample_rate_hz == 24_000
    assert terminal_audio.generation == 1
    assert terminal_audio.sequence == 5
    assert terminal_audio.is_final is True
    assert isinstance(transport.frames[4], AssistantResponseCompletedFrame)


async def test_empty_failed_response_shows_a_visible_retry_prompt() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )

    await bridge.handle_event(
        ResponseFailed(
            event_id="failed",
            context=event_context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
            error="first response text deadline exceeded after 5.000s",
        )
    )

    assert transport.frames == [
        AssistantTextFrame(
            text="刚才没有及时响应，请再说一次。",
            generation=1,
        ),
        AssistantSpeechCancelledFrame(generation=1, reason="failed"),
    ]
    assert transport.frames[-1].model_dump()["reason"] == "failed"


async def test_failed_response_does_not_replace_already_streamed_text() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )
    now = datetime.now(UTC)
    await bridge.handle_event(
        DisplayContentDelta(
            event_id="partial",
            context=event_context(),
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
            delta="我查一下，",
        )
    )
    await bridge.handle_event(
        ResponseFailed(
            event_id="failed",
            context=event_context(),
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            error="provider failed",
        )
    )

    assert transport.frames == [
        AssistantTextFrame(text="我查一下，", generation=1),
        AssistantSpeechCancelledFrame(generation=1, reason="failed"),
    ]
    assert transport.frames[-1].model_dump()["reason"] == "failed"


async def test_partial_input_transcript_is_forwarded_before_turn_commit() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )

    await bridge.handle_event(
        InputTranscriptDelta(
            event_id="input-partial-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            text="今天北京",
            delta="北京",
            transcript_revision=2,
        )
    )

    assert len(transport.frames) == 1
    frame = transport.frames[0]
    assert isinstance(frame, UserTranscriptFrame)
    assert frame.text == "今天北京"
    assert frame.generation == 1
    assert frame.is_final is False
    assert frame.turn_id == "turn-1"
    assert frame.transcript_revision == 2


async def test_spoken_content_is_streamed_as_cumulative_tts_text() -> None:
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
    )
    now = datetime.now(UTC)

    for sequence, delta in enumerate(("很久以前，", "有一只小鸟。"), start=1):
        await bridge.handle_event(
            SpokenContentDelta(
                event_id=f"spoken-{sequence}",
                context=event_context(),
                conversation_sequence=sequence,
                occurred_at=now,
                response_id="response-1",
                response_sequence=sequence,
                delta=delta,
            )
        )

    assert transport.frames == [
        AssistantSpeechTextFrame(
            text="很久以前，",
            generation=1,
        ),
        AssistantSpeechTextFrame(
            text="很久以前，有一只小鸟。",
            generation=1,
        ),
    ]


async def test_text_input_waits_for_projection_before_requesting_response() -> None:
    conversation = RecordingConversation()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
    )

    input_task = asyncio.create_task(bridge.handle_inbound(UserTextFrame(text="你好")))
    while not conversation.commands:
        await asyncio.sleep(0)
    append = conversation.commands[0]
    assert isinstance(append, AppendItem)
    item = item_from_draft(
        append.draft,
        sequence=7,
        recorded_at=datetime.now(UTC),
    )
    await bridge.handle_event(
        ItemProjected(
            event_id="projected",
            context=append.context,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            item_id=item.item_id,
            thread_sequence=item.sequence,
            thread_version=item.thread_version,
        )
    )
    await input_task

    assert isinstance(conversation.commands[1], RequestResponse)
    assert conversation.commands[1].minimum_thread_sequence == 7
    assert isinstance(transport.frames[0], UserTranscriptFrame)


async def test_explicit_stop_cancels_the_active_response_without_creating_a_user_turn() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    active_context = event_context(response_id="response-1")
    await bridge.handle_event(
        ResponseStarted(
            event_id="started-for-explicit-stop",
            context=active_context,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
        )
    )

    await bridge.handle_inbound(CancelAssistantResponseFrame())

    assert len(conversation.commands) == 1
    cancelled = conversation.commands[0]
    assert isinstance(cancelled, CancelResponse)
    assert cancelled.response_id == "response-1"
    assert cancelled.reason == "user_stop"


async def test_text_follow_up_cancels_the_active_response_before_starting_another() -> None:
    conversation = RecordingConversation()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=transport,
    )

    initial = asyncio.create_task(
        bridge.handle_inbound(UserTextFrame(text="北京今天天气怎么样？"))
    )
    while not conversation.commands:
        await asyncio.sleep(0)
    first_append = conversation.commands[0]
    first_item = item_from_draft(
        first_append.draft,
        sequence=1,
        recorded_at=datetime.now(UTC),
    )
    await bridge.handle_event(
        ItemProjected(
            event_id="projected-initial",
            context=first_append.context,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            item_id=first_item.item_id,
            thread_sequence=1,
            thread_version=1,
        )
    )
    await initial
    first_response = conversation.commands[1]
    await bridge.handle_event(
        ResponseStarted(
            event_id="started-initial",
            context=replace(first_response.context, response_id=first_response.response_id),
            conversation_sequence=2,
            occurred_at=datetime.now(UTC),
            response_id=first_response.response_id,
            response_sequence=1,
        )
    )

    follow_up = asyncio.create_task(
        bridge.handle_inbound(UserTextFrame(text="补充一下明天的。"))
    )
    async with asyncio.timeout(0.2):
        while len(conversation.commands) < 4:
            await asyncio.sleep(0)

    cancelled, follow_up_append = conversation.commands[2:4]
    assert isinstance(cancelled, CancelResponse)
    assert cancelled.response_id == first_response.response_id
    assert cancelled.reason == "text_barge_in"
    assert isinstance(follow_up_append, AppendItem)
    follow_up_item = item_from_draft(
        follow_up_append.draft,
        sequence=3,
        recorded_at=datetime.now(UTC),
    )
    await bridge.handle_event(
        ItemProjected(
            event_id="projected-follow-up",
            context=follow_up_append.context,
            conversation_sequence=3,
            occurred_at=datetime.now(UTC),
            item_id=follow_up_item.item_id,
            thread_sequence=3,
            thread_version=3,
        )
    )
    await follow_up

    assert isinstance(conversation.commands[4], RequestResponse)
    assert conversation.commands[4].context.generation == 2


async def test_transport_detach_cancels_live_response_before_recovery() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    await bridge.handle_event(
        ResponseStarted(
            event_id="response-started-1",
            context=event_context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
        )
    )

    await bridge.handle_detached()
    await bridge.handle_detached()

    assert len(conversation.commands) == 1
    cancelled = conversation.commands[0]
    assert isinstance(cancelled, CancelResponse)
    assert cancelled.response_id == "response-1"
    assert cancelled.reason == "transport_detached"


async def test_playback_completion_reports_full_spoken_delivery() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        SpokenContentDelta(
            event_id="spoken",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
            delta="你好世界",
        )
    )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio",
            context=response_context,
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=200_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )

    await bridge.handle_inbound(
        PlaybackProgressFrame(generation=1, finished=True, started=True)
    )

    command = conversation.commands[-1]
    assert isinstance(command, ReportPlaybackProgress)
    assert command.speech_id == "response:response-1"
    assert command.delivered_text_end == len("你好世界")
    assert command.played_audio_end_us == 200_000
    assert command.completed is True


async def test_playback_start_is_reported_before_audio_generation_completes() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        SpokenContentDelta(
            event_id="spoken-start",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
            delta="你好世界",
        )
    )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio-start",
            context=response_context,
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=200_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )

    await bridge.handle_inbound(
        PlaybackProgressFrame(generation=1, finished=False, started=True)
    )

    command = conversation.commands[-1]
    assert isinstance(command, ReportPlaybackProgress)
    assert command.speech_id == "response:response-1"
    assert command.delivered_text_end == 0
    assert command.played_audio_end_us == 0
    assert command.completed is False


async def test_playback_interruption_projects_client_audio_position_to_text_prefix() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        SpokenContentDelta(
            event_id="spoken-interrupted",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
            delta="一二三四五六七八九十",
        )
    )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio-interrupted",
            context=response_context,
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=200_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )

    await bridge.handle_inbound(
        PlaybackProgressFrame(
            generation=1,
            finished=False,
            stopped=True,
            played_audio_end_us=100_000,
        )
    )

    command = conversation.commands[-1]
    assert isinstance(command, ReportPlaybackProgress)
    assert command.delivered_text_end == 5
    assert command.played_audio_end_us == 100_000
    assert command.precision is PlaybackPrecision.ESTIMATED
    assert command.completed is False


async def test_v2_playback_uses_output_epoch_speech_identity_and_exact_samples() -> None:
    conversation = RecordingConversation()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation,
        transport=RecordingTransport(),
    )
    now = datetime.now(UTC)
    response_context = event_context()
    await bridge.handle_event(
        SpokenContentDelta(
            event_id="spoken-v2",
            context=response_context,
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
            delta="一二三四五六七八九十",
        )
    )
    await bridge.handle_event(
        AudioDelta(
            event_id="audio-v2",
            context=response_context,
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            speech_id="response:response-1",
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=200_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"audio",
            ),
            segment_index=0,
        )
    )

    await bridge.handle_inbound(
        PlaybackProgressV2(
            output_epoch="output-1",
            speech_id="response:response-1",
            generation=1,
            phase="stopped",
            played_position_samples=2_400,
        )
    )

    command = conversation.commands[-1]
    assert isinstance(command, ReportPlaybackProgress)
    assert command.delivered_text_end == 5
    assert command.played_audio_end_us == 100_000
    assert command.precision is PlaybackPrecision.EXACT
    assert command.completed is False
