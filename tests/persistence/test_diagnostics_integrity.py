from __future__ import annotations

import os
import uuid

import pytest

from server.application.runtime import ApplicationRuntime
from server.observability.telemetry import (
    InMemoryDebugLogStore,
    InMemoryTelemetryStore,
    RuntimeDebugLog,
    RuntimeTelemetry,
    TelemetryIdentity,
)
from server.persistence.postgres import PostgresPersistence
from server.persistence.postgres.schema import apply_migrations


async def test_long_telemetry_session_pages_without_losing_full_summary() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, max_queue_size=6000)
    await runtime.start()
    try:
        session = runtime.bind(TelemetryIdentity("t", "u", "d", "long", "long"))
        for index in range(5003):
            session.record(f"event-{index}")
        await runtime.flush()
        first = await store.session_detail("long")
        assert first.summary.event_count == 5003
        assert len(first.events) == 5000
        second = await store.session_detail("long", after_event_id=first.next_cursor)
        assert second.summary.event_count == 5003
        assert len(second.events) == 3
        assert second.next_cursor is None
        assert not {e.event_id for e in first.events} & {e.event_id for e in second.events}
        with pytest.raises(ValueError, match="cursor"):
            await store.session_detail("long", after_event_id="wrong-session")
    finally:
        await runtime.close()


async def test_debug_log_cursor_returns_remaining_entries() -> None:
    store = InMemoryDebugLogStore()
    runtime = RuntimeDebugLog(store)
    await runtime.start()
    try:
        session = runtime.bind("long")
        for index in range(5):
            session.log("turn", "decision", str(index))
        await runtime.flush()
        first = await store.session_timeline("long", limit=2)
        second = await store.session_timeline("long", limit=2, after_event_id=first[-1].event_id)
        third = await store.session_timeline("long", limit=2, after_event_id=second[-1].event_id)
        assert [entry.summary for entry in (*first, *second, *third)] == [str(i) for i in range(5)]
    finally:
        await runtime.close()


async def test_postgres_session_delete_rolls_back_all_sources_on_failure() -> None:
    dsn = os.getenv("VOICEAGENT_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires a PostgreSQL test DSN")
    import asyncpg

    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemKind,
        ConversationItemStatus,
        JournalScope,
        TextContent,
    )
    from server.core.interaction_context import InteractionContext
    from server.persistence.postgres import PostgresDebugLogStore, PostgresTelemetryStore
    schema = "diagnostics_test_" + uuid.uuid4().hex
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    runtime = None
    try:
        async with pool.acquire() as connection:
            await apply_migrations(connection, schema=schema)
        telemetry = RuntimeTelemetry(PostgresTelemetryStore(pool, schema=schema))
        debug = RuntimeDebugLog(PostgresDebugLogStore(pool, schema=schema))
        await telemetry.start()
        await debug.start()
        runtime = ApplicationRuntime(PostgresPersistence(pool, schema=schema), telemetry, debug_log=debug, pool=pool, postgres_schema=schema)
        telemetry.bind(TelemetryIdentity("t", "u", "d", "s", "s")).record("test")
        debug.bind("s").log("turn", "test", "keep on rollback")
        await telemetry.flush()
        await debug.flush()
        from dataclasses import replace
        seed = (await runtime.diagnostics.session_detail("s")).events[0]
        await telemetry.flush()
        await PostgresTelemetryStore(pool, schema=schema).append_batch(tuple(replace(seed, event_id=f"event-{index:05d}", sequence=index + 2, monotonic_ns=seed.monotonic_ns + index + 1) for index in range(5001)))
        page = await runtime.diagnostics.session_detail("s")
        assert page.summary.event_count == 5002
        assert len(page.events) == 5000
        remaining = await runtime.diagnostics.session_detail("s", after_event_id=page.next_cursor)
        assert len(remaining.events) == 2
        assert remaining.summary.event_count == 5002
        assert remaining.next_cursor is None
        logs = await runtime.debug_log_query.session_timeline("s", limit=1)
        assert await runtime.debug_log_query.session_timeline("s", after_event_id=logs[0].event_id) == ()
        scope = JournalScope(tenant_id="t", user_id="u", thread_id="s")
        await runtime.journal.append(ConversationItemDraft(item_id="item-test", context=InteractionContext(tenant_id="t", user_id="u", device_id="d", voice_session_id="s", thread_id="s", turn_id="turn-1", generation=1), kind=ConversationItemKind.USER_INPUT, status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent("keep"),)))
        async with pool.acquire() as connection:
            await connection.execute(f'''CREATE FUNCTION {schema}.reject_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected delete failure'; END $$''')
            await connection.execute(f"CREATE TRIGGER reject_delete BEFORE DELETE ON {schema}.runtime_telemetry_records FOR EACH ROW EXECUTE FUNCTION {schema}.reject_delete()")
        with pytest.raises(Exception, match="injected delete failure"):
            await runtime.delete_session_history(["s"], tenant_id="t", user_id="u")
        assert await runtime.journal.read(scope)
        assert await runtime.debug_log_query.session_timeline("s")
        assert await runtime.diagnostics.session_detail("s")
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        if runtime:
            await runtime.close()
        else:
            await pool.close()
