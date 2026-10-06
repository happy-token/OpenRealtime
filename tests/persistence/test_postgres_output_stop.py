"""Actual PostgreSQL operation fencing, using only a unique test schema."""

import asyncio
import os
import uuid
from dataclasses import replace

import pytest
import pytest_asyncio

from server.persistence.postgres.schema import render_migrations
from server.persistence.postgres.speech_delivery import PostgresSpeechDeliveryStore
from tests.realtime.test_output_stop_storage import confirmed, requested


@pytest_asyncio.fixture
async def stop_database():
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN")
    if os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1" or not dsn:
        pytest.skip("requires isolated PostgreSQL test DSN")
    import asyncpg

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
    schema = "output_stop_test_" + uuid.uuid4().hex
    try:
        async with pool.acquire() as connection:
            await connection.execute(f'CREATE SCHEMA "{schema}"')
            migration = next(
                sql for sql in render_migrations(schema) if ".speech_output_stop_records" in sql
            )
            await connection.execute(migration)
            await connection.execute(migration)  # Additive migration replay.
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await pool.close()


async def test_postgres_stop_confirmation_survives_new_store_and_request_replay(stop_database):
    pool, schema = stop_database
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    request, receipt = requested(), confirmed(requested())
    assert store.output_stop_durable
    await store.record_output_stop(request)
    await store.record_output_stop(receipt)
    recreated = PostgresSpeechDeliveryStore(pool, schema=schema)
    assert await recreated.get_output_stop(request.context, request.stop_command_id) == receipt
    assert await recreated.record_output_stop(request) == receipt
    assert await recreated.record_output_stop(receipt) == receipt
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(f'SELECT revision FROM "{schema}".speech_output_stop_records')
            == 2
        )


async def test_postgres_stop_scope_and_immutable_target(stop_database):
    pool, schema = stop_database
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    request = requested()
    await store.record_output_stop(request)
    for field in ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id"):
        other_context = replace(request.context, **{field: "other"})
        assert await store.get_output_stop(other_context, request.stop_command_id) is None
        other = replace(request, context=other_context)
        await store.record_output_stop(other)
        assert await store.get_output_stop(other_context, request.stop_command_id) == other
    for changes in (
        {"output_epoch": "other"},
        {"speech_id": "other"},
        {"context": replace(request.context, turn_id="other")},
        {"context": replace(request.context, generation=99)},
    ):
        with pytest.raises(ValueError):
            await store.record_output_stop(replace(request, **changes))
    assert await store.get_output_stop(request.context, request.stop_command_id) == request


async def test_postgres_concurrent_request_and_confirmation_cannot_downgrade(stop_database):
    pool, schema = stop_database
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    request = requested()
    receipt = confirmed(request)
    results = await asyncio.gather(
        *(store.record_output_stop(receipt if i % 2 else request) for i in range(40))
    )
    assert all(item.state in {"STOP_REQUESTED", "STOP_CONFIRMED"} for item in results)
    assert await store.get_output_stop(request.context, request.stop_command_id) == receipt
    with pytest.raises(ValueError):
        await store.record_output_stop(replace(receipt, played_position_samples=1))


async def test_postgres_conflicting_terminal_results_keep_first_commit(stop_database):
    pool, schema = stop_database
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    request = requested()
    await store.record_output_stop(request)
    receipt = confirmed(request)
    unknown = replace(request, state="STOP_UNKNOWN", failure_reason="receipt_deadline")
    results = await asyncio.gather(
        store.record_output_stop(receipt), store.record_output_stop(unknown), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    successful = next(result for result in results if not isinstance(result, BaseException))
    assert await store.get_output_stop(request.context, request.stop_command_id) == successful


async def test_postgres_stop_write_joins_parent_transaction_rollback(stop_database):
    pool, schema = stop_database
    request = requested()
    async with pool.acquire() as connection:
        with pytest.raises(RuntimeError, match="rollback"):
            async with connection.transaction():
                await PostgresSpeechDeliveryStore(connection, schema=schema).record_output_stop(
                    request
                )
                raise RuntimeError("rollback")
    assert (
        await PostgresSpeechDeliveryStore(pool, schema=schema).get_output_stop(
            request.context, request.stop_command_id
        )
        is None
    )


async def test_postgres_delete_stop_facts_preserves_other_scopes_and_rolls_back(stop_database):
    pool, schema = stop_database
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    request = requested()
    ctx = request.context
    matching = [ctx, replace(ctx, device_id="other-device")]
    others = [
        replace(ctx, **{field: "other"})
        for field in ("tenant_id", "user_id", "thread_id", "voice_session_id")
    ]
    for context in matching + others:
        await store.record_output_stop(replace(request, context=context))
    scope = {
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user_id,
        "thread_id": ctx.thread_id,
        "voice_session_id": ctx.voice_session_id,
    }
    async with pool.acquire() as connection:
        with pytest.raises(RuntimeError, match="rollback"):
            async with connection.transaction():
                assert (
                    await PostgresSpeechDeliveryStore(
                        connection, schema=schema
                    ).delete_output_stop_facts(**scope)
                    == 2
                )
                raise RuntimeError("rollback")
    for context in matching + others:
        assert await store.get_output_stop(context, request.stop_command_id) is not None
    assert await store.delete_output_stop_facts(**scope) == 2
    for context in matching:
        assert await store.get_output_stop(context, request.stop_command_id) is None
    for context in others:
        assert await store.get_output_stop(context, request.stop_command_id) is not None


async def test_postgres_runtime_session_purge_rolls_back_stop_facts_with_diagnostics(stop_database):
    from server.application.runtime import ApplicationRuntime
    from server.observability.telemetry import RuntimeDebugLog, RuntimeTelemetry, TelemetryIdentity
    from server.persistence.postgres import (
        PostgresDebugLogStore,
        PostgresPersistence,
        PostgresTelemetryStore,
    )
    from server.persistence.postgres.schema import apply_migrations

    pool, schema = stop_database
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    stop_store = PostgresSpeechDeliveryStore(pool, schema=schema)
    telemetry = RuntimeTelemetry(PostgresTelemetryStore(pool, schema=schema))
    debug = RuntimeDebugLog(PostgresDebugLogStore(pool, schema=schema))
    await telemetry.start()
    await debug.start()
    runtime = ApplicationRuntime(
        PostgresPersistence(pool, schema=schema),
        telemetry,
        debug_log=debug,
        speech_deliveries=stop_store,
        pool=pool,
        postgres_schema=schema,
    )
    fact = confirmed(requested())
    ctx = fact.context
    try:
        await stop_store.record_output_stop(fact)
        telemetry.bind(
            TelemetryIdentity(
                ctx.tenant_id, ctx.user_id, ctx.device_id, ctx.voice_session_id, ctx.thread_id
            )
        ).record("test")
        debug.bind(ctx.voice_session_id).log("output", "test", "keep on rollback")
        await telemetry.flush()
        await debug.flush()
        async with pool.acquire() as connection:
            await connection.execute(
                f'''CREATE FUNCTION "{schema}".reject_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected delete failure'; END $$'''
            )
            await connection.execute(
                f'CREATE TRIGGER reject_delete BEFORE DELETE ON "{schema}".runtime_telemetry_records FOR EACH ROW EXECUTE FUNCTION "{schema}".reject_delete()'
            )
        with pytest.raises(Exception, match="injected delete failure"):
            await runtime.delete_session_history(
                [ctx.voice_session_id], tenant_id="admin", user_id="admin"
            )
        assert await stop_store.get_output_stop(ctx, fact.stop_command_id) == fact
        assert await runtime.debug_log_query.session_timeline(ctx.voice_session_id)
        assert await runtime.diagnostics.session_detail(ctx.voice_session_id)
        async with pool.acquire() as connection:
            await connection.execute(
                f'DROP TRIGGER reject_delete ON "{schema}".runtime_telemetry_records'
            )
        result = await runtime.delete_session_history(
            [ctx.voice_session_id], tenant_id="admin", user_id="admin"
        )
        assert result["deleted_output_stop_facts"] == 1
        assert await stop_store.get_output_stop(ctx, fact.stop_command_id) is None
        assert await runtime.diagnostics.session_detail(ctx.voice_session_id) is None
    finally:
        # The fixture owns this pool. Stop runtime workers without closing it before schema cleanup.
        await telemetry.close()
        await debug.close()
