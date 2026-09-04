from __future__ import annotations

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    DisplayContent,
    InMemoryConversationJournal,
    SpokenContent,
    StructuredContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendItem,
    DeliverItem,
    DeliveryMode,
    DeliveryPriority,
    DeliveryTiming,
    InMemoryRealtimeConversation,
    ItemDeliveryCompleted,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemProjected,
    JournaledRealtimeConversation,
    ResponseRequested,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
)
from server.realtime.errors import ContextVisibilityError


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        worker_id="worker-1",
    )


def agent_result() -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id="item-agent-result-1",
        context=context(),
        kind=ConversationItemKind.DELEGATION_RESULT,
        status=ConversationItemStatus.COMPLETED,
        producer="agent-task-supervisor",
        content=(StructuredContent({"result": "上海明天有小雨。"}),),
    )


def delivery() -> DeliverItem:
    return DeliverItem(
        command_id="command-deliver-1",
        idempotency_key="deliver-item-1",
        context=context(),
        item_id="item-agent-result-1",
        delivery_id="delivery-1",
    )


def test_agent_result_delivery_defaults_to_model_response_when_idle() -> None:
    command = delivery()

    assert command.mode is DeliveryMode.MODEL_RESPONSE
    assert command.timing is DeliveryTiming.WHEN_IDLE
    assert command.priority is DeliveryPriority.NORMAL


async def test_delivery_requires_the_item_to_be_projected() -> None:
    conversation = InMemoryRealtimeConversation(context=context())

    with pytest.raises(ContextVisibilityError, match="has not been projected"):
        await conversation.send(delivery())

    await conversation.close()


async def test_default_delivery_requests_a_response_after_projection_barrier() -> None:
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-agent-result-1",
            context=context(),
            draft=agent_result(),
        )
    )
    projected = await anext(events)
    assert isinstance(projected, ItemProjected)

    await conversation.send(delivery())

    queued = await anext(events)
    started = await anext(events)
    requested = await anext(events)
    assert isinstance(queued, ItemDeliveryQueued)
    assert queued.item_id == projected.item_id
    assert queued.minimum_thread_sequence == projected.thread_sequence
    assert queued.mode is DeliveryMode.MODEL_RESPONSE
    assert queued.timing is DeliveryTiming.WHEN_IDLE
    assert isinstance(started, ItemDeliveryStarted)
    assert isinstance(requested, ResponseRequested)
    assert requested.minimum_thread_sequence == projected.thread_sequence
    assert requested.context.worker_id == "worker-1"

    await conversation.close()


@pytest.mark.parametrize(
    "mode",
    [DeliveryMode.DISPLAY_ONLY, DeliveryMode.SILENT],
)
async def test_non_spoken_delivery_modes_complete_without_requesting_a_model_response(
    mode: DeliveryMode,
) -> None:
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-agent-result-1",
            context=context(),
            draft=agent_result(),
        )
    )
    await anext(events)

    await conversation.send(
        DeliverItem(
            command_id=f"command-{mode.value}",
            idempotency_key=f"delivery-{mode.value}",
            context=context(),
            item_id="item-agent-result-1",
            delivery_id=f"delivery-{mode.value}",
            mode=mode,
        )
    )

    emitted = [await anext(events) for _ in range(3)]
    assert isinstance(emitted[0], ItemDeliveryQueued)
    assert isinstance(emitted[1], ItemDeliveryStarted)
    assert isinstance(emitted[2], ItemDeliveryCompleted)
    assert emitted[2].mode is mode

    await conversation.close()


async def test_speech_delivery_uses_the_projected_item_text_without_a_model_response() -> None:
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-agent-result-1",
            context=context(),
            draft=agent_result(),
        )
    )
    await anext(events)

    await conversation.send(
        DeliverItem(
            command_id="command-speech-1",
            idempotency_key="delivery-speech-1",
            context=context(),
            item_id="item-agent-result-1",
            delivery_id="delivery-speech-1",
            mode=DeliveryMode.SPEECH,
        )
    )

    emitted = [await anext(events) for _ in range(7)]
    assert isinstance(emitted[0], ItemDeliveryQueued)
    assert isinstance(emitted[1], ItemDeliveryStarted)
    assert isinstance(emitted[2], SpeechStarted)
    assert isinstance(emitted[3], SpeechTextAccepted)
    assert emitted[3].delta == "上海明天有小雨。"
    assert isinstance(emitted[4], SpeechTextCommitted)
    assert isinstance(emitted[5], SpeechPlaybackProgress)
    assert isinstance(emitted[6], ItemDeliveryCompleted)

    await conversation.close()


async def test_speech_delivery_prefers_explicit_spoken_content_over_display_and_semantic() -> None:
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-agent-result-1",
            context=context(),
            draft=ConversationItemDraft(
                item_id="item-agent-result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent-task-supervisor",
                content=(TextContent("完整语义内容，包含格式和诊断明细。"),),
                display=DisplayContent(markdown="## 完成\n\n包含诊断明细"),
                spoken=SpokenContent(text="任务已经完成。"),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="command-speech-1",
            idempotency_key="delivery-speech-1",
            context=context(),
            item_id="item-agent-result-1",
            delivery_id="delivery-speech-1",
            mode=DeliveryMode.SPEECH,
        )
    )

    emitted = [await anext(events) for _ in range(7)]
    assert isinstance(emitted[3], SpeechTextAccepted)
    assert emitted[3].delta == "任务已经完成。"

    await conversation.close()
