from __future__ import annotations

import asyncio

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendSpeechText,
    CancelSpeech,
    CommitSpeech,
    InMemoryRealtimeConversation,
    InterruptedContextPolicy,
    SpeechCancelled,
    SpeechContextPolicy,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
    StartSpeech,
)


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


def context_for_thread(thread_id: str) -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id=thread_id,
        turn_id="turn-1",
        generation=1,
    )


async def test_start_speech_opens_one_correlated_speech_output() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()

    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    event = await anext(events)
    assert isinstance(event, SpeechStarted)
    assert event.speech_id == "speech-1"
    assert event.context_policy is SpeechContextPolicy.AUTO
    assert event.conversation_sequence == 1

    await conversation.close()


async def test_start_speech_defaults_to_auto_context_and_delivered_only_interruption() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()

    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
            source_item_id="item-agent-result-1",
        )
    )

    started = await anext(events)
    assert isinstance(started, SpeechStarted)
    assert started.source_item_id == "item-agent-result-1"
    assert started.context_policy is SpeechContextPolicy.AUTO
    assert started.interrupted_context_policy is InterruptedContextPolicy.DELIVERED_ONLY

    await conversation.close()


async def test_command_from_another_thread_is_rejected_before_it_emits_an_event() -> None:
    conversation = InMemoryRealtimeConversation(context=context())

    with pytest.raises(ValueError, match="different realtime conversation scope"):
        await conversation.send(
            StartSpeech(
                command_id="command-start-1",
                idempotency_key="start-speech-1",
                context=context_for_thread("thread-2"),
                speech_id="speech-1",
            )
        )

    await conversation.close()


async def test_retried_start_speech_is_idempotent() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()
    start = StartSpeech(
        command_id="command-start-1",
        idempotency_key="start-speech-1",
        context=context(),
        speech_id="speech-1",
    )

    await conversation.send(start)
    await conversation.send(start)
    await conversation.send(
        StartSpeech(
            command_id="command-start-2",
            idempotency_key="start-speech-2",
            context=context(),
            speech_id="speech-2",
        )
    )

    first = await anext(events)
    second = await anext(events)
    assert first.speech_id == "speech-1"
    assert second.speech_id == "speech-2"
    assert second.conversation_sequence == 2

    await conversation.close()


async def test_append_speech_text_accepts_the_next_ordered_delta() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await anext(events)

    await conversation.send(
        AppendSpeechText(
            command_id="command-text-1",
            idempotency_key="speech-text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="任务已经完成",
        )
    )

    accepted = await anext(events)
    assert isinstance(accepted, SpeechTextAccepted)
    assert accepted.speech_id == "speech-1"
    assert accepted.text_sequence == 1
    assert accepted.delta == "任务已经完成"
    assert accepted.conversation_sequence == 2

    await conversation.close()


async def test_append_speech_text_rejects_a_sequence_gap() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    with pytest.raises(ValueError, match="expected speech text sequence 1"):
        await conversation.send(
            AppendSpeechText(
                command_id="command-text-2",
                idempotency_key="speech-text-2",
                context=context(),
                speech_id="speech-1",
                text_sequence=2,
                delta="跳过第一段",
            )
        )

    await conversation.close()


async def test_commit_speech_closes_text_input_with_complete_spoken_content() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="command-text-1",
            idempotency_key="speech-text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="任务已经完成",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="command-text-2",
            idempotency_key="speech-text-2",
            context=context(),
            speech_id="speech-1",
            text_sequence=2,
            delta="，测试全部通过。",
        )
    )

    await conversation.send(
        CommitSpeech(
            command_id="command-commit-1",
            idempotency_key="commit-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    emitted = [await anext(events) for _ in range(4)]
    committed = emitted[-1]
    assert isinstance(committed, SpeechTextCommitted)
    assert committed.speech_id == "speech-1"
    assert committed.spoken_text == "任务已经完成，测试全部通过。"
    assert committed.conversation_sequence == 4

    await conversation.close()


async def test_cancel_speech_settles_the_accepted_text_without_completing_delivery() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="command-text-1",
            idempotency_key="speech-text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="只接受了这一段",
        )
    )

    await conversation.send(
        CancelSpeech(
            command_id="command-cancel-1",
            idempotency_key="cancel-speech-1",
            context=context(),
            speech_id="speech-1",
            reason="barge_in",
        )
    )

    emitted = [await anext(events) for _ in range(3)]
    cancelled = emitted[-1]
    assert isinstance(cancelled, SpeechCancelled)
    assert cancelled.speech_id == "speech-1"
    assert cancelled.accepted_text == "只接受了这一段"
    assert cancelled.reason == "barge_in"

    with pytest.raises(ValueError, match="speech output is not active"):
        await conversation.send(
            AppendSpeechText(
                command_id="command-text-2",
                idempotency_key="speech-text-2",
                context=context(),
                speech_id="speech-1",
                text_sequence=2,
                delta="取消后不能再追加",
            )
        )

    await conversation.close()


async def test_terminal_speech_identity_cannot_be_reused_for_a_new_output() -> None:
    conversation = InMemoryRealtimeConversation(context=context())
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        CancelSpeech(
            command_id="command-cancel-1",
            idempotency_key="cancel-speech-1",
            context=context(),
            speech_id="speech-1",
            reason="cancelled",
        )
    )

    with pytest.raises(ValueError, match="speech output identity was already used"):
        await conversation.send(
            StartSpeech(
                command_id="command-start-2",
                idempotency_key="start-speech-2",
                context=context(),
                speech_id="speech-1",
            )
        )

    await conversation.close()


async def test_full_event_queue_applies_backpressure_until_the_consumer_advances() -> None:
    conversation = InMemoryRealtimeConversation(context=context(), event_queue_size=1)
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="command-start-1",
            idempotency_key="start-speech-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    blocked_send = asyncio.create_task(
        conversation.send(
            StartSpeech(
                command_id="command-start-2",
                idempotency_key="start-speech-2",
                context=context(),
                speech_id="speech-2",
            )
        )
    )
    await asyncio.sleep(0)
    assert blocked_send.done() is False

    assert (await anext(events)).speech_id == "speech-1"
    await asyncio.wait_for(blocked_send, timeout=0.1)
    assert (await anext(events)).speech_id == "speech-2"

    await conversation.close()
