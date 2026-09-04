from __future__ import annotations

from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    DisplayContent,
    InMemoryConversationJournal,
    JournalConflict,
    JournalScope,
    SpokenContent,
    StructuredContent,
    TextContent,
    ThreadVersionConflict,
)
from server.core.interaction_context import InteractionContext


def context(*, tenant_id: str = "tenant-1", user_id: str = "user-1") -> InteractionContext:
    return InteractionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


def user_item(item_id: str = "item-1", *, text: str = "hello") -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id=item_id,
        context=context(),
        kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="conversation-kernel",
        content=(TextContent(text),),
    )


@pytest.mark.asyncio
async def test_append_assigns_server_sequence_and_scoped_read_is_ordered() -> None:
    journal = InMemoryConversationJournal()
    first = await journal.append(user_item())
    second = await journal.append(
        ConversationItemDraft(
            item_id="item-2",
            context=replace(context(), response_id="response-1"),
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="native-realtime-engine",
            content=(TextContent("hi"),),
        ),
        expected_thread_version=1,
    )

    items = await journal.read(JournalScope.from_context(context()))

    assert (first.item.sequence, second.item.sequence) == (1, 2)
    assert (first.item.thread_version, second.item.thread_version) == (1, 2)
    assert [item.item_id for item in items] == ["item-1", "item-2"]


@pytest.mark.asyncio
async def test_identical_item_retry_is_idempotent_but_changed_content_conflicts() -> None:
    journal = InMemoryConversationJournal()
    first = await journal.append(user_item())
    retried = await journal.append(user_item(), expected_thread_version=0)

    assert retried.created is False
    assert retried.item == first.item
    assert await journal.thread_version(JournalScope.from_context(context())) == 1

    with pytest.raises(JournalConflict):
        await journal.append(user_item(text="changed"))


@pytest.mark.asyncio
async def test_expected_thread_version_rejects_lost_update() -> None:
    journal = InMemoryConversationJournal()
    await journal.append(user_item())

    with pytest.raises(ThreadVersionConflict) as captured:
        await journal.append(
            replace(user_item("item-2"), content=(TextContent("next"),)),
            expected_thread_version=0,
        )

    assert captured.value.expected == 0
    assert captured.value.actual == 1


@pytest.mark.asyncio
async def test_scope_prevents_cross_tenant_and_cross_user_history_reads() -> None:
    journal = InMemoryConversationJournal()
    await journal.append(user_item())

    assert await journal.read(
        JournalScope(tenant_id="tenant-2", user_id="user-1", thread_id="thread-1")
    ) == ()


@pytest.mark.asyncio
async def test_delete_threads_removes_selected_scope_and_item_id_index() -> None:
    journal = InMemoryConversationJournal()
    await journal.append(user_item())
    scope = JournalScope.from_context(context())

    deleted = await journal.delete_threads([scope])

    assert deleted == 1
    assert await journal.read(scope) == ()
    retried = await journal.append(user_item())
    assert retried.created is True
    assert retried.item.sequence == 1
    assert await journal.read(
        JournalScope(tenant_id="tenant-1", user_id="user-2", thread_id="thread-1")
    ) == ()


@pytest.mark.asyncio
async def test_model_projection_excludes_internal_items_and_preserves_semantic_content() -> None:
    journal = InMemoryConversationJournal()
    await journal.append(user_item())
    await journal.append(
        ConversationItemDraft(
            item_id="delegation-1",
            context=context().for_worker("worker-1"),
            kind=ConversationItemKind.DELEGATION_REQUESTED,
            status=ConversationItemStatus.COMMITTED,
            producer="agent-task-supervisor",
            visibility=frozenset({ConversationVisibility.INTERNAL}),
            content=(StructuredContent({"instruction": "inspect project"}),),
        )
    )

    projection = await journal.project_for_model(JournalScope.from_context(context()))

    assert [item.item_id for item in projection.items] == ["item-1"]
    assert projection.thread_version == 2


@pytest.mark.asyncio
async def test_assistant_item_persists_distinct_display_and_spoken_representations() -> None:
    journal = InMemoryConversationJournal()
    draft = ConversationItemDraft(
        item_id="assistant-1",
        context=replace(context(), response_id="response-1"),
        kind=ConversationItemKind.ASSISTANT_OUTPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="cascaded-realtime-engine",
        content=(
            TextContent("检查完成，共修改三个文件，全部测试通过。"),
            StructuredContent({"changed_files": 3, "tests": "passed"}),
        ),
        display=DisplayContent(markdown="## 已完成\n\n- 修改 3 个文件\n- 测试通过"),
        spoken=SpokenContent(text="检查完成，修改了三个文件，测试全部通过。"),
    )

    appended = await journal.append(draft)

    assert appended.item.content == draft.content
    assert appended.item.display == draft.display
    assert appended.item.spoken == draft.spoken
    with pytest.raises(JournalConflict):
        await journal.append(
            replace(
                draft,
                spoken=SpokenContent(text="检查完成。"),
            )
        )
