from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.conversation_journal.models import item_from_draft
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendAudio,
    AppendSpeechText,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CancelResponse,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    DialogueStateChanged,
    DisplayContentDelta,
    InputTranscriptCompleted,
    ItemDeliveryCompleted,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemProjected,
    ProjectCommittedItem,
    RealtimeCapabilityFailed,
    ReportPlaybackProgress,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseStarted,
    SpeechAudioCompleted,
    SpeechAudioDelta,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
    SpokenContentDelta,
    StartSpeech,
    ToolRequested,
)
from server.realtime.capabilities import LegacyTtsCapabilityAdapter
from server.realtime.native import NativeRealtimeEngine
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryStatus,
)
from server.speech.tts import SynthesizedAudioChunk
from server.tools.clock_source import ClockToolSource
from server.tools.registry import ToolRegistry
from server.turn_policy.states import DialogueState


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


class RecordingProviderSession:
    def __init__(self) -> None:
        self.messages = []
        self.closed = False
        self.event_queue = asyncio.Queue()

    async def send(self, message) -> None:
        self.messages.append(message)

    async def events(self):
        while True:
            event = await self.event_queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True
        await self.event_queue.put(None)


class RecordingProvider:
    def __init__(self) -> None:
        self.session = RecordingProviderSession()

    async def open(self, *, context, profile):
        del context, profile
        return self.session


async def next_event(events, event_type):
    while True:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        if isinstance(event, event_type):
            return event


async def test_native_provider_events_emit_dialogue_state_timeline() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    events = conversation.events()
    await provider.session.event_queue.put(
        {"type": "input_audio_buffer.speech_started", "item_id": "user-1"}
    )
    listening = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(listening, DialogueStateChanged)
    assert (listening.from_state, listening.to_state) == (
        DialogueState.IDLE,
        DialogueState.LISTEN,
    )

    await provider.session.event_queue.put(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "user-1"}
    )
    waiting = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(waiting, DialogueStateChanged)
    assert waiting.to_state is DialogueState.WAIT

    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    await provider.session.event_queue.put(
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    speaking = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ResponseStarted)

    await provider.session.event_queue.put(
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    idle = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(idle, DialogueStateChanged)
    assert idle.to_state is DialogueState.IDLE
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ResponseCompleted)
    await conversation.close()


async def test_native_close_cancels_active_response_before_event_stream_ends() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    await provider.session.event_queue.put(
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    events = conversation.events()
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)

    await conversation.close()

    cancelled = await next_event(events, ResponseCancelled)
    assert cancelled.reason == "conversation_closed"
    with pytest.raises(StopAsyncIteration):
        await anext(events)


async def test_native_provider_event_stream_close_is_a_public_failure() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    await provider.session.event_queue.put(
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    events = conversation.events()
    await next_event(events, ResponseStarted)

    await provider.session.close()

    failure = await next_event(events, RealtimeCapabilityFailed)
    assert failure.capability == "native_provider"
    assert failure.error == "provider event stream closed"
    await conversation.close()


class EchoDuplexTts:
    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for text in text_stream:
            yield SynthesizedAudioChunk(
                pcm16=text.encode(),
                sample_rate_hz=24_000,
                is_final=False,
            )


async def test_native_engine_maps_audio_to_official_realtime_append() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    audio = b"\x01\x00" * 512

    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=context(),
            frame=AudioFrame(
                stream_id="input-1",
                sequence=0,
                timestamp_us=0,
                duration_us=32_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=16_000,
                channels=1,
                data=audio,
            ),
        )
    )

    assert provider.session.messages == [
        {
            "type": "input_audio_buffer.append",
            "event_id": "audio-1",
            "audio": base64.b64encode(b"\x01\x00" * 768).decode("ascii"),
        }
    ]
    await conversation.close()


async def test_native_engine_projects_committed_item_before_response_context() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    draft = ConversationItemDraft(
        item_id="user-1",
        context=context(),
        kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="test",
        content=(TextContent("你好"),),
    )
    item = item_from_draft(draft, sequence=1, recorded_at=datetime.now(UTC))

    await conversation.send(
        ProjectCommittedItem(
            command_id="project-1",
            idempotency_key="project-1",
            context=context(),
            item=item,
        )
    )

    assert provider.session.messages == [
        {
            "type": "conversation.item.create",
            "event_id": "project-1",
            "item": {
                "id": "user-1",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "你好"}],
            },
        }
    ]
    projected = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(projected, ItemProjected)
    assert projected.item_id == "user-1"
    assert projected.thread_sequence == 1
    await conversation.close()


async def test_native_engine_does_not_duplicate_its_own_assistant_item_projection() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
            output_item_id="assistant-1",
        )
    )
    item = item_from_draft(
        ConversationItemDraft(
            item_id="assistant-1",
            context=response_context,
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="realtime-turn-controller",
            content=(TextContent("已经由原生模型生成"),),
        ),
        sequence=1,
        recorded_at=datetime.now(UTC),
    )

    await conversation.send(
        ProjectCommittedItem(
            command_id="project-assistant-1",
            idempotency_key="project-assistant-1",
            context=response_context,
            item=item,
        )
    )

    assert [message["type"] for message in provider.session.messages] == [
        "response.create"
    ]
    projected = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(projected, ItemProjected)
    await conversation.close()


async def test_native_engine_maps_provider_response_to_canonical_stream() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    draft = ConversationItemDraft(
        item_id="user-1",
        context=context(),
        kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="test",
        content=(TextContent("你好"),),
    )
    item = item_from_draft(draft, sequence=1, recorded_at=datetime.now(UTC))
    await conversation.send(
        ProjectCommittedItem(
            command_id="project-1",
            idempotency_key="project-1",
            context=context(),
            item=item,
        )
    )
    events = conversation.events()
    await anext(events)
    response_context = replace(context(), response_id="response-1")

    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=1,
            output_item_id="assistant-1",
        )
    )

    assert provider.session.messages[-1] == {
        "type": "response.create",
        "event_id": "respond-1",
        "response": {
            "conversation": "auto",
            "metadata": {
                "voiceagent_response_id": "response-1",
                "voiceagent_output_item_id": "assistant-1",
            },
        },
    }
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.output_text.delta",
            "response_id": "provider-response-1",
            "delta": "你好，",
        },
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "provider-response-1",
            "delta": "你好。",
        },
        {
            "type": "response.output_audio.delta",
            "response_id": "provider-response-1",
            "item_id": "provider-item-1",
            "delta": base64.b64encode(b"\x01\x00" * 240).decode("ascii"),
        },
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
    ):
        await provider.session.event_queue.put(provider_event)

    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    assert isinstance(await next_event(events, DisplayContentDelta), DisplayContentDelta)
    assert isinstance(await next_event(events, SpokenContentDelta), SpokenContentDelta)
    audio = await next_event(events, AudioDelta)
    assert audio.frame.duration_us == 10_000
    assert audio.speech_id == "response:response-1"
    assert isinstance(await next_event(events, ResponseCompleted), ResponseCompleted)
    await conversation.close()


async def test_native_cancel_before_provider_admission_is_not_lost() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )

    await conversation.send(
        CancelResponse(
            command_id="cancel-1",
            idempotency_key="cancel-1",
            context=response_context,
            response_id="response-1",
            reason="superseded",
        )
    )

    assert [message["type"] for message in provider.session.messages] == [
        "response.create"
    ]
    await provider.session.event_queue.put(
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    events = conversation.events()
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    assert provider.session.messages[-1] == {
        "type": "response.cancel",
        "event_id": "cancel-1",
        "response_id": "provider-response-1",
    }
    await provider.session.event_queue.put(
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "cancelled",
                "status_details": {"reason": "superseded"},
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    cancelled = await next_event(events, ResponseCancelled)
    assert isinstance(cancelled, ResponseCancelled)
    assert cancelled.reason == "superseded"
    await conversation.close()


async def test_native_input_transcription_commits_one_canonical_user_turn() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=context(),
            frame=AudioFrame(
                stream_id="input-1",
                sequence=0,
                timestamp_us=0,
                duration_us=32_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=16_000,
                channels=1,
                data=b"\x00\x00" * 512,
            ),
        )
    )
    await provider.session.event_queue.put(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "provider-user-1",
            "transcript": "今天天气怎么样",
        }
    )

    event = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(event, InputTranscriptCompleted)
    assert event.text == "今天天气怎么样"
    assert event.transcript_revision == 1
    assert event.provider_endpoint_observed is True
    await conversation.close()


async def test_native_audio_transcript_is_also_streamed_as_display_fallback() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "provider-response-1",
            "delta": "原生语音文本",
        },
    ):
        await provider.session.event_queue.put(provider_event)
    events = conversation.events()
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    display = await next_event(events, DisplayContentDelta)
    spoken = await next_event(events, SpokenContentDelta)
    assert isinstance(display, DisplayContentDelta)
    assert display.delta == "原生语音文本"
    assert isinstance(spoken, SpokenContentDelta)
    await conversation.close()


async def test_native_transcript_keeps_context_captured_at_provider_speech_start() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(), profile=None
    )
    first = context()
    second = replace(context(), turn_id="turn-2", generation=2)
    for sequence, command_context in enumerate((first, second)):
        await conversation.send(
            AppendAudio(
                command_id=f"audio-{sequence}",
                idempotency_key=f"audio-{sequence}",
                context=command_context,
                frame=AudioFrame(
                    stream_id="input-1",
                    sequence=sequence,
                    timestamp_us=sequence * 32_000,
                    duration_us=32_000,
                    encoding=AudioEncoding.PCM_S16LE,
                    sample_rate_hz=16_000,
                    channels=1,
                    data=b"\x00\x00" * 512,
                ),
            )
        )
        if sequence == 0:
            await provider.session.event_queue.put(
                {
                    "type": "input_audio_buffer.speech_started",
                    "item_id": "provider-user-1",
                }
            )
            await asyncio.sleep(0)
    await provider.session.event_queue.put(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "provider-user-1",
            "transcript": "第一轮",
        }
    )

    transcript = await next_event(conversation.events(), InputTranscriptCompleted)
    assert isinstance(transcript, InputTranscriptCompleted)
    assert transcript.context.generation == 1
    assert transcript.context.turn_id == "turn-1"
    await conversation.close()


async def test_native_function_arguments_done_emits_canonical_tool_request() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        tools=ToolRegistry([ClockToolSource()]),
    ).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.function_call_arguments.done",
            "response_id": "provider-response-1",
            "call_id": "call-1",
            "name": "get_current_datetime",
            "arguments": '{"timezone":"Asia/Shanghai"}',
        },
    ):
        await provider.session.event_queue.put(provider_event)
    events = conversation.events()
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    requested = await next_event(events, ToolRequested)
    assert isinstance(requested, ToolRequested)
    assert requested.context.call_id == "call-1"
    assert requested.tool_name == "get_current_datetime"
    assert requested.tool_version == "1.0.0"
    assert requested.arguments == {"timezone": "Asia/Shanghai"}
    await conversation.close()


async def test_native_tool_result_continues_one_logical_response() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        tools=ToolRegistry([ClockToolSource()]),
    ).open(
        context=context(), profile=None
    )
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
            output_item_id="assistant-1",
        )
    )
    events = conversation.events()
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.function_call_arguments.done",
            "response_id": "provider-response-1",
            "call_id": "call-1",
            "name": "get_current_datetime",
            "arguments": '{"timezone":"Asia/Shanghai"}',
        },
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
    ):
        await provider.session.event_queue.put(provider_event)
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    assert isinstance(await next_event(events, ToolRequested), ToolRequested)
    await asyncio.sleep(0)

    tool_context = replace(response_context, call_id="call-1")
    tool_result = item_from_draft(
        ConversationItemDraft(
            item_id="tool-result-1",
            context=tool_context,
            kind=ConversationItemKind.TOOL_RESULT,
            status=ConversationItemStatus.COMPLETED,
            producer="voice-runtime-tool-controller",
            content=(TextContent("12:30"),),
        ),
        sequence=1,
        recorded_at=datetime.now(UTC),
    )
    await conversation.send(
        ProjectCommittedItem(
            command_id="project-tool-result",
            idempotency_key="project-tool-result",
            context=tool_context,
            item=tool_result,
        )
    )
    assert isinstance(await next_event(events, ItemProjected), ItemProjected)
    assert [message["type"] for message in provider.session.messages[-2:]] == [
        "conversation.item.create",
        "response.create",
    ]

    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-2",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "provider-response-2",
            "delta": "现在是十二点半。",
        },
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-2",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
    ):
        await provider.session.event_queue.put(provider_event)
    emitted = []
    while not any(isinstance(event, ResponseCompleted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert any(isinstance(event, DisplayContentDelta) for event in emitted)
    assert any(isinstance(event, SpokenContentDelta) for event in emitted)
    assert not any(isinstance(event, ResponseStarted) for event in emitted)
    await conversation.close()


async def test_native_tool_result_waits_for_provider_turn_done_before_continuing() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        tools=ToolRegistry([ClockToolSource()]),
    ).open(context=context(), profile=None)
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.function_call_arguments.done",
            "response_id": "provider-response-1",
            "call_id": "call-1",
            "name": "get_current_datetime",
            "arguments": "{}",
        },
    ):
        await provider.session.event_queue.put(provider_event)
    events = conversation.events()
    await next_event(events, ToolRequested)
    tool_context = replace(response_context, call_id="call-1")
    tool_result = item_from_draft(
        ConversationItemDraft(
            item_id="tool-result-1",
            context=tool_context,
            kind=ConversationItemKind.TOOL_RESULT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("12:30"),),
        ),
        sequence=1,
        recorded_at=datetime.now(UTC),
    )
    await conversation.send(
        ProjectCommittedItem(
            command_id="project-tool-result",
            idempotency_key="project-tool-result",
            context=tool_context,
            item=tool_result,
        )
    )

    assert provider.session.messages[-1]["type"] == "conversation.item.create"
    await provider.session.event_queue.put(
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    while provider.session.messages[-1]["type"] != "response.create":
        await asyncio.sleep(0)
    assert provider.session.messages[-1]["event_id"] == "continue:provider-response-1"
    await conversation.close()


@pytest.mark.parametrize("phase", ["started", "progress", "stopped"])
async def test_native_barge_in_preserves_delivered_prefix_and_truncates_provider(phase) -> None:
    provider = RecordingProvider()
    deliveries = InMemorySpeechDeliveryStore()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="respond-1",
            idempotency_key="respond-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=0,
            output_item_id="assistant-1",
        )
    )
    events = conversation.events()
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-response-1",
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        },
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "provider-response-1",
            "delta": "你好世界",
        },
        {
            "type": "response.output_audio.delta",
            "response_id": "provider-response-1",
            "item_id": "provider-item-1",
            "delta": base64.b64encode(b"\x01\x00" * 240).decode("ascii"),
        },
    ):
        await provider.session.event_queue.put(provider_event)
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), DisplayContentDelta
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), SpokenContentDelta
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), AudioDelta)

    await conversation.send(
        ReportPlaybackProgress(
            command_id="playback-1",
            idempotency_key="playback-1",
            context=response_context,
            speech_id="response:response-1",
            delivered_text_end=len("你好"),
            played_audio_end_us=10_000,
            output_epoch="output",
            played_position_samples=240,
            sample_rate_hz=24000,
            observed_at_ns=1,
            started=phase == "started",
            stopped=phase == "stopped",
        )
    )
    progress = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(progress, SpeechPlaybackProgress)
    assert progress.delivered_speech_transcript == "你好"
    assert progress.output_epoch == "output" and progress.played_position_samples == 240
    assert progress.sample_rate_hz == 24000
    assert progress.started == (phase == "started") and progress.stopped == (phase == "stopped")
    await conversation.send(
        CancelResponse(
            command_id="cancel-1",
            idempotency_key="cancel-1",
            context=response_context,
            response_id="response-1",
            reason="barge_in",
        )
    )

    assert provider.session.messages[-2:] == [
        {
            "type": "conversation.item.truncate",
            "event_id": "cancel-1:truncate",
            "item_id": "provider-item-1",
            "content_index": 0,
            "audio_end_ms": 10,
        },
        {
            "type": "response.cancel",
            "event_id": "cancel-1",
            "response_id": "provider-response-1",
        },
    ]
    await provider.session.event_queue.put(
        {
            "type": "response.done",
            "response": {
                "id": "provider-response-1",
                "status": "cancelled",
                "status_details": {"reason": "barge_in"},
                "metadata": {"voiceagent_response_id": "response-1"},
            },
        }
    )
    cancelled = await next_event(events, ResponseCancelled)
    assert isinstance(cancelled, ResponseCancelled)
    record = await deliveries.get("response:response-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.INTERRUPTED
    assert record.delivered_speech_transcript == "你好"
    await conversation.close()


async def test_native_engine_accepts_external_duplex_speech_text() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    events = conversation.events()

    await conversation.send(
        StartSpeech(
            command_id="speech-start",
            idempotency_key="speech-start",
            context=context(),
            speech_id="speech-1",
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), SpeechStarted)
    await conversation.send(
        AppendSpeechText(
            command_id="speech-text-1",
            idempotency_key="speech-text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="AB",
        )
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), SpeechTextAccepted
    )
    audio = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(audio, SpeechAudioDelta)
    assert audio.frame.data == b"AB"
    await conversation.send(
        CommitSpeech(
            command_id="speech-commit",
            idempotency_key="speech-commit",
            context=context(),
            speech_id="speech-1",
        )
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), SpeechTextCommitted
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), SpeechAudioCompleted
    )
    await conversation.send(
        ReportPlaybackProgress(
            command_id="speech-playback",
            idempotency_key="speech-playback",
            context=context(),
            speech_id="speech-1",
            delivered_text_end=2,
            played_audio_end_us=100,
            completed=True,
        )
    )
    progress = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(progress, SpeechPlaybackProgress)
    assert progress.delivered_speech_transcript == "AB"
    await conversation.close()


async def test_native_engine_delivers_projected_agent_result_through_model() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(provider=provider).open(
        context=context(),
        profile=None,
    )
    draft = ConversationItemDraft(
        item_id="result-1",
        context=context(),
        kind=ConversationItemKind.DELEGATION_RESULT,
        status=ConversationItemStatus.COMPLETED,
        producer="agent-runtime",
        content=(TextContent("后台任务完成"),),
    )
    item = item_from_draft(draft, sequence=1, recorded_at=datetime.now(UTC))
    events = conversation.events()
    await conversation.send(
        ProjectCommittedItem(
            command_id="project-result",
            idempotency_key="project-result",
            context=context(),
            item=item,
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ItemProjected)
    await conversation.send(
        DeliverItem(
            command_id="deliver-result",
            idempotency_key="deliver-result",
            context=context(),
            item_id="result-1",
            delivery_id="delivery-1",
            output_item_id="assistant-result-1",
        )
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), ItemDeliveryQueued
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), ItemDeliveryStarted
    )
    assert provider.session.messages[-1]["response"]["metadata"] == {
        "voiceagent_response_id": "delivery:delivery-1",
        "voiceagent_output_item_id": "assistant-result-1",
    }
    for provider_event in (
        {
            "type": "response.created",
            "response": {
                "id": "provider-delivery-1",
                "metadata": {"voiceagent_response_id": "delivery:delivery-1"},
            },
        },
        {
            "type": "response.done",
            "response": {
                "id": "provider-delivery-1",
                "status": "completed",
                "metadata": {"voiceagent_response_id": "delivery:delivery-1"},
            },
        },
    ):
        await provider.session.event_queue.put(provider_event)
    assert isinstance(await next_event(events, ResponseStarted), ResponseStarted)
    assert isinstance(await next_event(events, ResponseCompleted), ResponseCompleted)
    completed = await next_event(events, ItemDeliveryCompleted)
    assert isinstance(completed, ItemDeliveryCompleted)
    assert completed.item_id == "result-1"
    await conversation.close()


async def test_native_engine_direct_speech_delivery_uses_optional_tts_lane() -> None:
    provider = RecordingProvider()
    conversation = await NativeRealtimeEngine(
        provider=provider,
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    item = item_from_draft(
        ConversationItemDraft(
            item_id="result-1",
            context=context(),
            kind=ConversationItemKind.DELEGATION_RESULT,
            status=ConversationItemStatus.COMPLETED,
            producer="agent-runtime",
            content=(TextContent("AB"),),
        ),
        sequence=1,
        recorded_at=datetime.now(UTC),
    )
    events = conversation.events()
    await conversation.send(
        ProjectCommittedItem(
            command_id="project-result",
            idempotency_key="project-result",
            context=context(),
            item=item,
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="speak-result",
            idempotency_key="speak-result",
            context=context(),
            item_id="result-1",
            delivery_id="speech-1",
            mode=DeliveryMode.SPEECH,
        )
    )

    emitted = []
    while len(emitted) < 10:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, ItemDeliveryCompleted):
            break
    assert any(isinstance(event, ResponseStarted) for event in emitted)
    assert "".join(
        event.delta for event in emitted if isinstance(event, SpokenContentDelta)
    ) == "AB"
    assert b"".join(
        event.frame.data for event in emitted if isinstance(event, AudioDelta)
    ) == b"AB"
    assert isinstance(emitted[-1], ItemDeliveryCompleted)
    await conversation.close()
