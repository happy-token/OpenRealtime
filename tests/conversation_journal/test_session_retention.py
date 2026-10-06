from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from server.conversation_journal import InMemoryConversationJournal, JournalScope
from server.persistence.postgres.conversation_journal import PostgresConversationJournal
from tests.conversation_journal.test_in_memory_journal import context, user_item


async def test_shared_thread_can_only_be_deleted_when_all_item_sessions_are_selected():
    journal = InMemoryConversationJournal()
    scope = JournalScope.from_context(context())
    await journal.append(user_item())
    await journal.append(replace(user_item("resumed-item"), context=replace(context(), voice_session_id="resumed")))
    assert await journal.delete_session_owned_threads([scope], ["voice-1"]) == 0
    assert len(await journal.read(scope)) == 2
    assert await journal.delete_session_owned_threads([scope], ["voice-1", "resumed"]) == 1
    assert not await journal.read(scope)


@pytest.mark.parametrize("shared", [True, False])
async def test_postgres_session_ownership_is_checked_under_thread_row_lock(shared):
    calls = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            calls.append("begin")
            yield
            calls.append("commit")

        async def fetchval(self, query, *arguments):
            if "FOR UPDATE" in query:
                calls.append("lock")
                return 2
            assert "SELECT EXISTS" in query and "voice_session_id = ANY" in query
            assert arguments[-1] == ["voice-1"]
            calls.append("ownership")
            return shared

        async def execute(self, query, *arguments):
            assert "DELETE FROM" in query
            calls.append("items deleted")

        async def fetch(self, query, *arguments):
            assert "DELETE FROM" in query
            calls.append("thread deleted")
            return [{"thread_id": "thread-1"}]

    journal = PostgresConversationJournal(Connection())
    assert await journal.delete_session_owned_threads([JournalScope.from_context(context())], ["voice-1"]) == (0 if shared else 1)
    assert calls == ["begin", "lock", "ownership", *([] if shared else ["items deleted", "thread deleted"]), "commit"]
