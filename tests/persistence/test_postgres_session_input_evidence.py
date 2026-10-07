"""Real PG original-Session evidence and additive partial index checks."""
import os
from dataclasses import replace

import pytest

from server.conversation_journal.input_evidence import read_session_input_evidence
from server.persistence.postgres import PostgresConversationJournal, apply_migrations
from tests.conversation_journal.test_session_input_evidence_query import record
from tests.persistence.test_postgres_conversation_journal import (
    postgres as postgres,  # noqa: PLC0414 - expose the shared pytest fixture
)
from tests.realtime.test_cascaded_capabilities import context

pytestmark = pytest.mark.skipif(os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
                               reason="requires owned PostgreSQL schema")


async def test_real_pg_input_evidence_reopen_pagination_and_cross_session(postgres):
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    ctx = context()
    one = await record(journal, ctx, "first")
    await record(journal, replace(ctx, voice_session_id="continued"), "other session")
    two = await record(journal, ctx, "second")
    reopened = PostgresConversationJournal(pool, schema=schema)
    first = await read_session_input_evidence(reopened, ctx.voice_session_id, limit=1)
    assert first["durable"] and first["records"][0]["item_id"] == one.item_id
    second = await read_session_input_evidence(reopened, ctx.voice_session_id, after_sequence=int(first["next_cursor"]), limit=1)
    assert second["next_cursor"] is None and second["records"][0]["item_id"] == two.item_id
    assert (await read_session_input_evidence(reopened, "missing"))["status"] == "not_collected"


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "thread_id"])
async def test_real_pg_ambiguous_input_scope_is_unavailable(postgres, field):
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await record(journal, context(), "mine")
    await record(journal, replace(context(), **{field: "foreign"}), "foreign")
    with pytest.raises(ValueError, match="ambiguous"):
        await read_session_input_evidence(journal, context().voice_session_id)


async def test_real_pg_wrong_input_index_predicate_is_not_accepted(postgres):
    pool, schema = postgres
    async with pool.acquire() as connection:
        await connection.execute(f'DROP INDEX "{schema}".conversation_items_input_evidence_read_idx')
        await connection.execute(f'''CREATE INDEX conversation_items_input_evidence_read_idx
            ON "{schema}".conversation_items (voice_session_id,tenant_id,user_id,thread_id,sequence)
            WHERE producer='other' ''')
        with pytest.raises(RuntimeError, match="input_evidence_read_idx"):
            await apply_migrations(connection, schema=schema)


async def test_actual_postgres_overview_preserves_causal_failure_groups(postgres):
    from server.persistence.postgres.runtime_telemetry import PostgresTelemetryStore
    from tests.test_diagnostic_module_health import verify_recorded_health

    pool, schema = postgres
    await verify_recorded_health(PostgresTelemetryStore(pool, schema=schema))
