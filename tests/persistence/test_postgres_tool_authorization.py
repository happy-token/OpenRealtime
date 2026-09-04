from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from server.persistence.postgres import PostgresToolAuthorizationStore, apply_migrations
from server.tools.canonical import RiskLevel, ToolEffect
from server.tools.policy_gateway import (
    Allow,
    ConfirmationChannel,
    ConfirmationRejected,
    DefaultToolPolicyGateway,
    GrantRejected,
    RequireConfirmation,
    ToolExecutor,
    ToolPolicyContext,
)
from tests.tools.test_policy_gateway import context, registry, request


pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest_asyncio.fixture
async def postgres() -> tuple[object, str]:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12)
    schema = f"voiceagent_tool_test_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    try:
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await pool.close()


@pytest.mark.asyncio
async def test_concurrent_policy_evaluation_returns_one_durable_grant(postgres) -> None:
    pool, schema = postgres

    async def handler(arguments: dict) -> str:
        return str(arguments)

    tools = registry(handler)
    gateway = DefaultToolPolicyGateway(
        tools,
        authorization_store=PostgresToolAuthorizationStore(pool, schema=schema),
    )

    decisions = await asyncio.gather(
        *(gateway.evaluate(request(), ToolPolicyContext()) for _ in range(30))
    )

    assert all(isinstance(decision, Allow) for decision in decisions)
    assert len({decision.grant.decision_id for decision in decisions}) == 1
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(
                f'SELECT count(*) FROM "{schema}".tool_policy_decisions'
            )
            == 1
        )
        assert (
            await connection.fetchval(
                f'SELECT count(*) FROM "{schema}".tool_execution_grants'
            )
            == 1
        )


@pytest.mark.asyncio
async def test_durable_grant_is_consumed_once_across_gateway_instances(postgres) -> None:
    pool, schema = postgres
    calls = 0

    async def handler(arguments: dict) -> str:
        nonlocal calls
        calls += 1
        return str(arguments)

    tools = registry(handler)
    store = PostgresToolAuthorizationStore(pool, schema=schema)
    first_gateway = DefaultToolPolicyGateway(tools, authorization_store=store)
    decision = await first_gateway.evaluate(request(), ToolPolicyContext())
    assert isinstance(decision, Allow)
    second_gateway = DefaultToolPolicyGateway(
        tools,
        authorization_store=PostgresToolAuthorizationStore(pool, schema=schema),
    )
    first_executor = ToolExecutor(tools, first_gateway)
    second_executor = ToolExecutor(tools, second_gateway)

    results = await asyncio.gather(
        first_executor.execute(request(), decision.grant),
        second_executor.execute(request(), decision.grant),
        return_exceptions=True,
    )

    assert calls == 1
    assert sum(isinstance(result, GrantRejected) for result in results) == 1


@pytest.mark.asyncio
async def test_pending_confirmation_survives_gateway_restart_and_replay_is_rejected(
    postgres,
) -> None:
    pool, schema = postgres

    async def handler(arguments: dict) -> str:
        return str(arguments)

    tools = registry(
        handler,
        risk=RiskLevel.HIGH,
        effects=frozenset({ToolEffect.COMMUNICATE_EXTERNAL}),
    )
    first = DefaultToolPolicyGateway(
        tools,
        authorization_store=PostgresToolAuthorizationStore(pool, schema=schema),
    )
    decision = await first.evaluate(request(), ToolPolicyContext())
    assert isinstance(decision, RequireConfirmation)

    recovered = DefaultToolPolicyGateway(
        tools,
        authorization_store=PostgresToolAuthorizationStore(pool, schema=schema),
    )
    allowed = await recovered.confirm(
        confirmation_id=decision.pending.confirmation_id,
        action_digest=request().arguments_digest,
        context=context(),
        channel=ConfirmationChannel.VOICE,
        approved=True,
    )

    assert isinstance(allowed, Allow)
    with pytest.raises(ConfirmationRejected):
        await first.confirm(
            confirmation_id=decision.pending.confirmation_id,
            action_digest=request().arguments_digest,
            context=context(),
            channel=ConfirmationChannel.VOICE,
            approved=True,
        )
