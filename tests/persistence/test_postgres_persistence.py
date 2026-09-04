from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentRunStarted,
    AgentRunHandle,
    AgentRunLocator,
    WorkspaceMode,
    utc_now,
)
from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.supervisor import (
    AGENT_RESULT_MESSAGE_TYPE,
    AgentTaskSupervisor,
)
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    AgentTaskPhase,
    DelegationRequest,
    IdempotencyConflict,
    RevisionConflict,
    TaskCreateDisposition,
)
from server.core.interaction_context import InteractionContext
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    JournalScope,
    TextContent,
)
from server.persistence.outbox import (
    OutboxConflict,
    OutboxLeaseLost,
    OutboxMessageDraft,
    OutboxStatus,
)
from server.persistence.postgres import (
    PostgresAgentTaskStore,
    PostgresOutboxStore,
    PostgresPersistence,
    apply_migrations,
    render_initial_migration,
)
from server.persistence.unit_of_work import PersistenceUnitOfWork


pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest_asyncio.fixture
async def postgres() -> tuple[object, str]:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12)
    schema = f"voiceagent_test_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    try:
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await pool.close()


def make_request(
    request_id: str,
    *,
    instruction: str = "Inspect project",
    force_new: bool = False,
) -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id=request_id,
        selection_plan=AgentSelectionPlan(
            plan_id="codex-first",
            version=1,
            primary=AgentCandidate("codex"),
        ),
        instruction=instruction,
        context=InteractionContext(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
            turn_id="turn-1",
            generation=1,
        ),
        workspace_root="/workspace",
        workspace_mode=WorkspaceMode.READ_ONLY,
        force_new=force_new,
    )


@pytest.mark.asyncio
async def test_dispatch_attempt_migration_upgrades_initial_schema(postgres) -> None:
    pool, _ = postgres
    schema = f"voiceagent_upgrade_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        try:
            await connection.execute(render_initial_migration(schema))
            before = await connection.fetchval(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = 'agent_tasks'
                  AND column_name = 'dispatch_attempt_count'
                """,
                schema,
            )
            await apply_migrations(connection, schema=schema)
            after = await connection.fetchval(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = 'agent_tasks'
                  AND column_name = 'dispatch_attempt_count'
                """,
                schema,
            )
        finally:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')

    assert before == 0
    assert after == 1


@pytest.mark.asyncio
async def test_concurrent_strong_idempotency_creates_one_task(postgres) -> None:
    pool, schema = postgres
    store = PostgresAgentTaskStore(pool, schema=schema)

    results = await asyncio.gather(
        *(store.create_or_get(make_request("same-request")) for _ in range(50))
    )

    assert len({result.record.worker_id for result in results}) == 1
    assert sum(result.disposition is TaskCreateDisposition.CREATED for result in results) == 1
    async with pool.acquire() as connection:
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_tasks') == 1


@pytest.mark.asyncio
async def test_concurrent_semantic_dedupe_creates_aliases_not_tasks(postgres) -> None:
    pool, schema = postgres
    store = PostgresAgentTaskStore(pool, schema=schema)

    results = await asyncio.gather(
        *(store.create_or_get(make_request(f"request-{index}")) for index in range(20))
    )

    assert len({result.record.worker_id for result in results}) == 1
    async with pool.acquire() as connection:
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_tasks') == 1
        assert (
            await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_task_request_keys')
            == 20
        )


@pytest.mark.asyncio
async def test_request_id_content_conflict_is_rejected(postgres) -> None:
    pool, schema = postgres
    store = PostgresAgentTaskStore(pool, schema=schema)
    await store.create_or_get(make_request("request-1"))

    with pytest.raises(IdempotencyConflict):
        await store.create_or_get(make_request("request-1", instruction="Different work"))


@pytest.mark.asyncio
async def test_force_new_does_not_replace_normal_semantic_dedupe_guard(postgres) -> None:
    pool, schema = postgres
    store = PostgresAgentTaskStore(pool, schema=schema)

    normal = await store.create_or_get(make_request("request-normal"))
    forced = await store.create_or_get(make_request("request-forced", force_new=True))
    later_retry = await store.create_or_get(make_request("request-retry"))

    assert forced.disposition is TaskCreateDisposition.CREATED
    assert forced.record.worker_id != normal.record.worker_id
    assert later_retry.disposition is TaskCreateDisposition.SEMANTIC_REUSE
    assert later_retry.record.worker_id == normal.record.worker_id
    async with pool.acquire() as connection:
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_tasks') == 2


@pytest.mark.asyncio
async def test_task_lifecycle_round_trips_handle_and_enforces_revision_cas(postgres) -> None:
    pool, schema = postgres
    store = PostgresAgentTaskStore(pool, schema=schema)
    accepted = (await store.create_or_get(make_request("request-lifecycle"))).record

    queued = await store.select_candidate(
        accepted.worker_id,
        expected_revision=accepted.revision,
        agent_name="codex",
        candidate_index=0,
    )
    with pytest.raises(RevisionConflict):
        await store.commit_backend(
            accepted.worker_id,
            expected_revision=accepted.revision,
            dispatch_token="dispatch-1",
        )
    starting = await store.commit_backend(
        accepted.worker_id,
        expected_revision=queued.revision,
        dispatch_token="dispatch-1",
    )
    handle = AgentRunHandle(
        worker_id=accepted.worker_id,
        dispatch_token="dispatch-1",
        locator=AgentRunLocator(
            driver_kind="codex_app_server",
            backend_session_id="thread-1",
            backend_run_id="turn-1",
        ),
        capabilities=AgentCapabilityDescriptor(
            driver_kind="codex_app_server",
            driver_version="test",
            protocol_version="2",
            capabilities=frozenset({AgentCapability.STATUS_LOOKUP}),
        ),
    )
    running = await store.attach_handle(
        accepted.worker_id,
        expected_revision=starting.revision,
        handle=handle,
    )
    succeeded = await store.transition(
        accepted.worker_id,
        expected_revision=running.revision,
        phase=AgentTaskPhase.SUCCEEDED,
        result="done",
    )

    assert succeeded.phase is AgentTaskPhase.SUCCEEDED
    assert succeeded.result == "done"
    assert succeeded.handle == handle
    assert succeeded.revision == accepted.revision + 4


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_task_and_outbox_together(postgres) -> None:
    pool, schema = postgres
    persistence = PostgresPersistence(pool, schema=schema)

    with pytest.raises(RuntimeError):
        async with persistence.unit_of_work() as unit:
            created = await unit.agent_tasks.create_or_get(make_request("request-1"))
            await unit.agent_events.append(
                AgentRunStarted(
                    worker_id=created.record.worker_id,
                    event_id="event-1",
                    sequence=1,
                    occurred_at=utc_now(),
                    locator=AgentRunLocator(
                        driver_kind="codex",
                        backend_session_id="thread-1",
                        backend_run_id="turn-1",
                    ),
                )
            )
            await unit.journal.append(
                ConversationItemDraft(
                    item_id="delegation-request-1",
                    context=make_request("request-1").context,
                    kind=ConversationItemKind.DELEGATION_REQUESTED,
                    status=ConversationItemStatus.COMMITTED,
                    producer="test",
                    visibility=frozenset({ConversationVisibility.INTERNAL}),
                    content=(TextContent("inspect project"),),
                )
            )
            await unit.outbox.enqueue(
                OutboxMessageDraft(
                    tenant_id="tenant-1",
                    aggregate_type="agent_task",
                    aggregate_id="worker-pending",
                    message_type="agent.dispatch",
                    dedupe_key="dispatch:request-1",
                    payload={"worker_id": "worker-pending"},
                )
            )
            raise RuntimeError("force rollback")

    async with pool.acquire() as connection:
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_tasks') == 0
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".outbox_messages') == 0
        assert (
            await connection.fetchval(
                f'SELECT count(*) FROM "{schema}".conversation_items'
            )
            == 0
        )
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_events') == 0


@pytest.mark.asyncio
async def test_outbox_claims_are_disjoint_and_fenced(postgres) -> None:
    pool, schema = postgres
    outbox = PostgresOutboxStore(pool, schema=schema)
    for index in range(10):
        await outbox.enqueue(
            OutboxMessageDraft(
                tenant_id="tenant-1",
                aggregate_type="agent_task",
                aggregate_id=f"worker-{index}",
                message_type="agent.dispatch",
                dedupe_key=f"dispatch:{index}",
                payload={"worker_id": f"worker-{index}"},
            )
        )

    first, second = await asyncio.gather(
        outbox.claim(owner="dispatcher-1", limit=10, lease_seconds=30),
        outbox.claim(owner="dispatcher-2", limit=10, lease_seconds=30),
    )
    claimed = (*first, *second)

    assert len(claimed) == 10
    assert len({message.outbox_id for message in claimed}) == 10
    message = claimed[0]
    delivered = await outbox.mark_delivered(
        message.outbox_id,
        owner=message.lease_owner or "",
        fencing_token=message.fencing_token,
    )
    assert delivered.status is OutboxStatus.DELIVERED
    with pytest.raises(OutboxLeaseLost):
        await outbox.mark_delivered(
            message.outbox_id,
            owner=message.lease_owner or "",
            fencing_token=message.fencing_token,
        )


@pytest.mark.asyncio
async def test_outbox_dedupe_reuses_identical_message_and_rejects_changed_payload(
    postgres,
) -> None:
    pool, schema = postgres
    outbox = PostgresOutboxStore(pool, schema=schema)
    draft = OutboxMessageDraft(
        tenant_id="tenant-1",
        aggregate_type="agent_task",
        aggregate_id="worker-1",
        message_type="agent.dispatch",
        dedupe_key="dispatch:worker-1",
        payload={"worker_id": "worker-1"},
    )

    first = await outbox.enqueue(draft)
    same = await outbox.enqueue(draft)

    assert same.outbox_id == first.outbox_id
    with pytest.raises(OutboxConflict):
        await outbox.enqueue(
            OutboxMessageDraft(
                tenant_id=draft.tenant_id,
                aggregate_type=draft.aggregate_type,
                aggregate_id=draft.aggregate_id,
                message_type=draft.message_type,
                dedupe_key=draft.dedupe_key,
                payload={"worker_id": "changed"},
            )
        )
    with pytest.raises(OutboxConflict):
        await outbox.enqueue(
            OutboxMessageDraft(
                tenant_id=draft.tenant_id,
                aggregate_type=draft.aggregate_type,
                aggregate_id=draft.aggregate_id,
                message_type=draft.message_type,
                dedupe_key=draft.dedupe_key,
                payload=draft.payload,
                schema_version=2,
            )
        )


@pytest.mark.asyncio
async def test_outbox_claim_filters_message_types(postgres) -> None:
    pool, schema = postgres
    outbox = PostgresOutboxStore(pool, schema=schema)
    for message_type in ("agent.dispatch.requested.v1", "journal.project.requested.v1"):
        await outbox.enqueue(
            OutboxMessageDraft(
                tenant_id="tenant-1",
                aggregate_type="test",
                aggregate_id=message_type,
                message_type=message_type,
                dedupe_key=message_type,
                payload={"type": message_type},
            )
        )

    claimed = await outbox.claim(
        owner="agent-dispatcher",
        limit=10,
        lease_seconds=30,
        message_types=frozenset({"agent.dispatch.requested.v1"}),
    )

    assert [message.message_type for message in claimed] == [
        "agent.dispatch.requested.v1"
    ]


@pytest.mark.asyncio
async def test_supervisor_commits_dispatch_then_concurrent_workers_start_once(
    postgres,
) -> None:
    pool, schema = postgres
    persistence = PostgresPersistence(pool, schema=schema)
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )

    submission = await supervisor.submit(make_request("request-supervised"))

    assert submission.record.phase is AgentTaskPhase.STARTING
    assert driver.start_count == 0
    async with pool.acquire() as connection:
        stored = await connection.fetchrow(
            f'SELECT phase, dispatch_attempt_count FROM "{schema}".agent_tasks'
        )
        outbox_status = await connection.fetchval(
            f'SELECT status FROM "{schema}".outbox_messages'
        )
    assert stored["phase"] == "starting"
    assert stored["dispatch_attempt_count"] == 0
    assert outbox_status == "pending"
    journal_items = await persistence.journal.read(
        JournalScope.from_context(submission.record.context)
    )
    assert len(journal_items) == 1
    assert journal_items[0].kind is ConversationItemKind.DELEGATION_REQUESTED
    assert journal_items[0].context.worker_id == submission.record.worker_id

    retry_without_driver = AgentTaskSupervisor(persistence=persistence, drivers={})
    retry = await retry_without_driver.submit(make_request("request-supervised-retry"))
    assert retry.record.worker_id == submission.record.worker_id
    await retry_without_driver.shutdown()

    first, second = await asyncio.gather(
        supervisor.dispatch_once(owner="dispatcher-1"),
        supervisor.dispatch_once(owner="dispatcher-2"),
    )

    assert len((*first, *second)) == 1
    assert driver.start_count == 1
    record = await supervisor.get(submission.record.worker_id)
    assert record is not None
    assert record.phase is AgentTaskPhase.RUNNING
    assert record.dispatch_attempt_count == 1
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(
                f'SELECT status FROM "{schema}".outbox_messages'
            )
            == "delivered"
        )
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_supervisor_rolls_back_task_when_dispatch_outbox_write_fails(
    postgres,
) -> None:
    pool, schema = postgres
    base = PostgresPersistence(pool, schema=schema)

    class FailingOutbox:
        async def enqueue(self, draft):
            del draft
            raise RuntimeError("injected outbox failure")

    class FailingPersistence:
        @property
        def agent_tasks(self):
            return base.agent_tasks

        @property
        def outbox(self):
            return base.outbox

        @property
        def agent_events(self):
            return base.agent_events

        @asynccontextmanager
        async def unit_of_work(self):
            async with base.unit_of_work() as unit:
                yield PersistenceUnitOfWork(
                    agent_tasks=unit.agent_tasks,
                    outbox=FailingOutbox(),
                    journal=unit.journal,
                    agent_events=unit.agent_events,
                    tool_authorizations=unit.tool_authorizations,
                )

    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=FailingPersistence(),
        drivers={"codex": driver},
    )

    with pytest.raises(RuntimeError, match="injected outbox failure"):
        await supervisor.submit(make_request("request-rollback-dispatch"))

    async with pool.acquire() as connection:
        assert await connection.fetchval(f'SELECT count(*) FROM "{schema}".agent_tasks') == 0
        assert (
            await connection.fetchval(
                f'SELECT count(*) FROM "{schema}".outbox_messages'
            )
            == 0
        )
        assert (
            await connection.fetchval(
                f'SELECT count(*) FROM "{schema}".conversation_items'
            )
            == 0
        )
    assert driver.start_count == 0
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_supervisor_commits_terminal_event_task_journal_and_delivery(postgres) -> None:
    pool, schema = postgres
    persistence = PostgresPersistence(pool, schema=schema)
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )
    submission = await supervisor.submit(make_request("request-terminal"))
    await supervisor.dispatch_once(owner="dispatcher")

    await driver.complete(submission.record.worker_id, "done")
    for _ in range(100):
        record = await supervisor.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0.005)

    assert record is not None
    assert record.phase is AgentTaskPhase.SUCCEEDED
    assert record.result == "done"
    async with pool.acquire() as connection:
        events = await connection.fetch(
            f'SELECT sequence FROM "{schema}".agent_events ORDER BY sequence'
        )
        journal_kinds = await connection.fetch(
            f'SELECT kind FROM "{schema}".conversation_items ORDER BY sequence'
        )
        delivery_count = await connection.fetchval(
            f"""
            SELECT count(*) FROM "{schema}".outbox_messages
            WHERE message_type = $1
            """,
            AGENT_RESULT_MESSAGE_TYPE,
        )

    assert [row["sequence"] for row in events] == [1, 2]
    assert [row["kind"] for row in journal_kinds] == [
        "delegation.requested",
        "delegation.result",
    ]
    assert delivery_count == 1
    await supervisor.shutdown()
