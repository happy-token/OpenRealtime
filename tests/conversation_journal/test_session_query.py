"""Session diagnosis pagination must not scan a shared thread's first page."""

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


def context(session_id="A", thread_id="thread"):
    return InteractionContext(tenant_id="tenant", user_id="user", device_id="device",
                              voice_session_id=session_id, thread_id=thread_id, turn_id="turn", generation=1)


async def append(journal, item_id, ctx, kind=ConversationItemKind.USER_INPUT):
    return await journal.append(ConversationItemDraft(item_id=item_id, context=ctx, kind=kind,
        status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent(item_id),)))


async def test_session_pages_are_exact_complete_and_skip_shared_thread_holes():
    journal = InMemoryConversationJournal()
    await append(journal, "A-1", context())
    for i in range(1005):
        await append(journal, f"B-{i}", context("B"))
    await append(journal, "A-2", context())
    await append(journal, "A-3", context())
    first = await journal.read_session_page("A", limit=2)
    assert [item.item_id for item in first.items] == ["A-1", "A-2"]
    assert first.next_sequence == 1007
    final = await journal.read_session_page("A", after_sequence=first.next_sequence, limit=2)
    assert [item.item_id for item in final.items] == ["A-3"]
    assert final.next_sequence is None
    missing = await journal.read_session_page("absent", limit=2)
    assert missing.items == () and missing.next_sequence is None


async def test_session_identity_rejects_conflicting_conversation_scopes_but_not_input_evidence():
    journal = InMemoryConversationJournal()
    await append(journal, "conversation", context())
    await append(journal, "evidence", context(thread_id="input-evidence"), ConversationItemKind.CORRECTION)
    assert len((await journal.read_session_page("A")).items) == 1
    await append(journal, "conflicting", replace(context(), tenant_id="other-tenant"))
    with pytest.raises(ValueError, match="ambiguous"):
        await journal.read_session_page("A")


async def test_session_query_index_tracks_idempotence_and_both_thread_deletion_paths():
    journal = InMemoryConversationJournal()
    await append(journal, "A-1", context())
    await append(journal, "A-1", context())
    assert len((await journal.read_session_page("A")).items) == 1
    assert await journal.delete_session_owned_threads((JournalScope.from_context(context()),), ("B",)) == 0
    assert len((await journal.read_session_page("A")).items) == 1
    assert await journal.delete_session_owned_threads((JournalScope.from_context(context()),), ("A",)) == 1
    assert (await journal.read_session_page("A")).items == ()
    await append(journal, "fresh", replace(context(), tenant_id="new-tenant"))
    assert len((await journal.read_session_page("A")).items) == 1
    assert await journal.delete_threads((JournalScope.from_context(replace(context(), tenant_id="new-tenant")),)) == 1
    assert (await journal.read_session_page("A")).items == ()


@pytest.mark.parametrize("after,limit", [(-1, 2), (2**63, 2), (0, 0), (0, 1001)])
async def test_session_query_has_bounded_cursor_and_page(after, limit):
    journal = InMemoryConversationJournal()
    with pytest.raises(ValueError):
        await journal.read_session_page("A", after_sequence=after, limit=limit)
