from __future__ import annotations

from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    JournalScope,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendItem,
    CancelResponse,
    ContextVisibilityError,
    InMemoryRealtimeConversation,
    ItemProjected,
    JournaledRealtimeConversation,
    ProjectCommittedItem,
    RequestResponse,
    ResponseCancelled,
    ResponseRequested,
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


def user_item() -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id="item-user-1",
        context=context(),
        kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="test-client",
        content=(TextContent("明天上海天气怎么样？"),),
    )


async def test_append_item_is_committed_before_the_engine_projects_it() -> None:
    journal = InMemoryConversationJournal()
    engine_conversation = InMemoryRealtimeConversation(context=context())
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=engine_conversation,
    )
    events = conversation.events()

    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-item-1",
            context=context(),
            draft=user_item(),
        )
    )

    committed_items = await journal.read(JournalScope.from_context(context()))
    projected = await anext(events)
    assert len(committed_items) == 1
    assert committed_items[0].sequence == 1
    assert isinstance(projected, ItemProjected)
    assert projected.item_id == committed_items[0].item_id
    assert projected.thread_sequence == committed_items[0].sequence
    assert projected.thread_version == committed_items[0].thread_version

    await conversation.close()


async def test_response_request_rejects_context_not_yet_projected_by_engine() -> None:
    conversation = InMemoryRealtimeConversation(context=context())

    with pytest.raises(ContextVisibilityError, match="requires thread sequence 1"):
        await conversation.send(
            RequestResponse(
                command_id="command-response-1",
                idempotency_key="request-response-1",
                context=context(),
                response_id="response-1",
                minimum_thread_sequence=1,
            )
        )

    await conversation.close()


async def test_response_request_is_accepted_after_required_context_is_projected() -> None:
    journal = InMemoryConversationJournal()
    engine_conversation = InMemoryRealtimeConversation(context=context())
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=engine_conversation,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="command-append-1",
            idempotency_key="append-item-1",
            context=context(),
            draft=user_item(),
        )
    )
    await anext(events)

    await conversation.send(
        RequestResponse(
            command_id="command-response-1",
            idempotency_key="request-response-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )

    requested = await anext(events)
    assert isinstance(requested, ResponseRequested)
    assert requested.response_id == "response-1"
    assert requested.context.response_id == "response-1"
    assert requested.minimum_thread_sequence == 1

    await conversation.close()


async def test_reference_conversation_cancels_an_admitted_response() -> None:
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-1",
            idempotency_key="append-1",
            context=context(),
            draft=user_item(),
        )
    )
    projected = await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="response-1",
            idempotency_key="response-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=projected.thread_sequence,
        )
    )
    await anext(events)

    await conversation.send(
        CancelResponse(
            command_id="cancel-1",
            idempotency_key="cancel-1",
            context=context(),
            response_id="response-1",
            reason="superseded",
        )
    )

    cancelled = await anext(events)
    assert isinstance(cancelled, ResponseCancelled)
    assert cancelled.reason == "superseded"
    await conversation.close()


async def test_external_caller_cannot_bypass_journal_with_projected_item() -> None:
    journal = InMemoryConversationJournal()
    committed = await journal.append(user_item())
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )

    with pytest.raises(TypeError, match="control-plane only"):
        await conversation.send(
            ProjectCommittedItem(
                command_id="forged-project-1",
                idempotency_key="forged-project-1",
                context=context(),
                item=committed.item,
            )
        )

    await conversation.close()


async def test_append_item_rejects_draft_from_another_voice_session_before_commit() -> None:
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=InMemoryRealtimeConversation(context=context()),
    )
    other_session_draft = replace(
        user_item(),
        context=replace(context(), voice_session_id="voice-2"),
    )

    with pytest.raises(ValueError, match="different realtime conversation scope"):
        await conversation.send(
            AppendItem(
                command_id="command-append-1",
                idempotency_key="append-item-1",
                context=context(),
                draft=other_session_draft,
            )
        )

    assert await journal.read(JournalScope.from_context(context())) == ()
    await conversation.close()
