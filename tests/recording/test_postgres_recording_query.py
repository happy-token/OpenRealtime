from __future__ import annotations

import os
from dataclasses import replace

import pytest

from server.persistence.postgres import PostgresConversationJournal, apply_migrations
from server.persistence.postgres.schema import render_migrations
from server.realtime.recording import recording_scope
from tests.persistence.test_postgres_conversation_journal import (
    postgres as postgres,  # noqa: PLC0414 - re-export fixture for injection
)
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import draft, recorded

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest.mark.asyncio
async def test_recording_query_actual_postgres_pagination_artifact_and_delete(postgres):
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    _, item = await recorded(journal)
    artifact = item.content[0].value["artifact_id"]
    assert await journal.find_recording_artifact(context().voice_session_id, artifact) == item
    assert await journal.find_recording_artifact("foreign-session", artifact) is None
    await journal.append(draft(item))
    first = await journal.read_recording_page(context().voice_session_id, limit=1)
    second = await journal.read_recording_page(
        context().voice_session_id, after_sequence=first.next_sequence, limit=1
    )
    assert first.items == (item,) and second.items[0].sequence == 2
    assert second.next_sequence is None
    with pytest.raises(ValueError, match="ambiguous"):
        await journal.find_recording_artifact(context().voice_session_id, artifact)
    await journal.delete_threads([recording_scope(context())])
    assert (await journal.read_recording_page(context().voice_session_id)).items == ()
    assert await journal.find_recording_artifact(context().voice_session_id, artifact) is None


@pytest.mark.asyncio
async def test_recording_query_actual_postgres_conflict_and_nested_timeout_restore(postgres):
    pool, schema = postgres
    async with pool.acquire() as connection:
        journal = PostgresConversationJournal(connection, schema=schema)
        _, item = await recorded(journal)
        async with connection.transaction():
            await connection.execute("SET LOCAL statement_timeout = '100ms'")
            assert (await journal.read_recording_page(context().voice_session_id)).items == (item,)
            assert (
                await journal.find_recording_artifact(
                    context().voice_session_id, item.content[0].value["artifact_id"]
                )
                == item
            )
            assert await connection.fetchval("SHOW statement_timeout") == "100ms"
        await journal.append(
            replace(draft(item), context=replace(item.context, tenant_id="foreign"))
        )
        with pytest.raises(ValueError):
            await journal.read_recording_page(context().voice_session_id)
        with pytest.raises(ValueError):
            await journal.find_recording_artifact(
                context().voice_session_id, item.content[0].value["artifact_id"]
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["session", "recording"])
async def test_migrations_reject_matching_columns_with_wrong_partial_predicate(postgres, name):
    pool, schema = postgres
    index = f"conversation_items_{name}_read_idx"
    async with pool.acquire() as connection:
        await connection.execute(f'DROP INDEX CONCURRENTLY "{schema}".{index}')
        await connection.execute(
            f'CREATE INDEX CONCURRENTLY {index} ON "{schema}".conversation_items '
            "(voice_session_id, tenant_id, user_id, thread_id, sequence) WHERE producer = 'wrong'"
        )
        with pytest.raises(RuntimeError, match="invalid or incompatible"):
            await apply_migrations(connection, schema=schema)
        await connection.execute(f'DROP INDEX CONCURRENTLY "{schema}".{index}')
        await apply_migrations(connection, schema=schema)


def test_recording_index_quotes_valid_reserved_schema():
    migration = next(sql for sql in render_migrations("user") if "recording_read_idx" in sql)
    assert 'ON "user".conversation_items' in migration
