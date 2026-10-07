from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace

import pytest
import pytest_asyncio

from server.agent_session.driver_protocol import (
    AgentRunLocator,
    AgentRunStarted,
    WorkspaceMode,
    utc_now,
)
from server.agent_session.event_store import AgentEventConflict, AgentEventGap
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    DelegationRequest,
)
from server.conversation_journal import (
    ArtifactReferenceContent,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    DisplayContent,
    JournalConflict,
    JournalScope,
    SpokenContent,
    StructuredContent,
    TextContent,
    ThreadVersionConflict,
)
from server.core.interaction_context import InteractionContext
from server.persistence.postgres import (
    PostgresAgentEventStore,
    PostgresConversationJournal,
    PostgresPersistence,
    PostgresSpeechDeliveryStore,
    apply_migrations,
)
from server.realtime import (
    InterruptedContextPolicy,
    PlaybackPrecision,
    SpeechContextPolicy,
)
from server.realtime.speech import SpeechDeliveryRecord, SpeechDeliveryStatus

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest_asyncio.fixture
async def postgres() -> tuple[object, str]:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12)
    schema = f"voiceagent_journal_test_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    try:
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await pool.close()


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=2,
        response_id="response-1",
    )


def item(item_id: str, text: str = "hello") -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id=item_id,
        context=context(),
        kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMPLETED,
        producer="conversation-kernel",
        content=(
            TextContent(text, language="zh-CN"),
            StructuredContent({"confidence": 0.98}),
            ArtifactReferenceContent(
                artifact_id="artifact-1",
                media_type="audio/pcm",
                size_bytes=3200,
                sha256="a" * 64,
            ),
        ),
        provider_metadata={"provider": "test"},
    )


def delegation_request() -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id="request-1",
        selection_plan=AgentSelectionPlan(
            plan_id="codex-first",
            version=1,
            primary=AgentCandidate("codex"),
        ),
        instruction="inspect project",
        context=replace(context(), response_id=None),
        workspace_root="/workspace",
        workspace_mode=WorkspaceMode.READ_ONLY,
    )


@pytest.mark.asyncio
async def test_postgres_journal_round_trips_typed_semantic_item(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)

    appended = await journal.append(item("item-1"), expected_thread_version=0)
    items = await journal.read(JournalScope.from_context(context()))

    assert appended.created is True
    assert items == (appended.item,)
    assert items[0].content[0] == TextContent("hello", language="zh-CN")
    assert items[0].content[1] == StructuredContent({"confidence": 0.98})
    assert items[0].content[2].artifact_id == "artifact-1"


@pytest.mark.asyncio
async def test_postgres_session_query_pages_only_original_session_and_rejects_ambiguity(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    original = item("A-1")
    await journal.append(original)
    await journal.append(replace(item("B-1"), context=replace(context(), voice_session_id="continued")))
    await journal.append(item("A-2"))
    await journal.append(item("A-3"))
    # Input evidence may use a distinct Journal thread; it is not dialogue identity.
    await journal.append(replace(item("evidence"), kind=ConversationItemKind.CORRECTION,
                                 context=replace(context(), thread_id="evidence-thread")))
    first = await journal.read_session_page("voice-1", limit=2)
    assert [entry.item_id for entry in first.items] == ["A-1", "A-2"]
    assert first.next_sequence == 3
    final = await journal.read_session_page("voice-1", after_sequence=first.next_sequence, limit=2)
    assert [entry.item_id for entry in final.items] == ["A-3"] and final.next_sequence is None
    continued = await journal.read_session_page("continued")
    assert [entry.item_id for entry in continued.items] == ["B-1"]
    assert (await journal.read_session_page("missing")).items == ()
    await journal.append(replace(item("other"), context=replace(context(), tenant_id="other-tenant")))
    with pytest.raises(ValueError, match="ambiguous"):
        await journal.read_session_page("voice-1")


@pytest.mark.asyncio
async def test_postgres_session_index_is_valid_idempotent_and_query_uses_it(postgres) -> None:
    pool, schema = postgres
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
        index = await connection.fetchrow(
            "SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) AS definition FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = $1 AND c.relname = 'conversation_items_session_read_idx'", schema,
        )
        assert index is not None and index["indisvalid"] is True
        assert "voice_session_id, tenant_id, user_id, thread_id, sequence" in index["definition"]
        async with connection.transaction():
            await connection.execute("SET LOCAL enable_seqscan = off")
            plan = await connection.fetch(
                f'EXPLAIN SELECT * FROM "{schema}".conversation_items '
                "WHERE voice_session_id = $1 AND tenant_id = $2 AND user_id = $3 AND thread_id = $4 "
                "AND kind IN ('user.input', 'assistant.output') AND sequence > $5 ORDER BY sequence LIMIT $6",
                "voice-1", "tenant-1", "user-1", "thread-1", 0, 3,
            )
        assert "conversation_items_session_read_idx" in str(plan)


@pytest.mark.asyncio
async def test_postgres_session_cursor_boundaries_and_delete_remove_query_results(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await journal.append(item("A-1"))
    for after, limit in [(-1, 2), (2**63, 2), (0, 0), (0, 1001)]:
        with pytest.raises(ValueError):
            await journal.read_session_page("voice-1", after_sequence=after, limit=limit)
    assert await journal.delete_threads((JournalScope.from_context(context()),)) == 1
    assert (await journal.read_session_page("voice-1")).items == ()


@pytest.mark.asyncio
async def test_postgres_session_page_works_inside_caller_transaction_without_timeout_leak(postgres) -> None:
    pool, schema = postgres
    async with pool.acquire() as connection:
        journal = PostgresConversationJournal(connection, schema=schema)
        async with connection.transaction():
            await connection.execute("SET LOCAL statement_timeout = '100ms'")
            await journal.append(item("nested-item"))
            page = await journal.read_session_page("voice-1")
            assert len(page.items) == 1
            assert await connection.fetchval("SHOW statement_timeout") == "100ms"
            await journal.append(item("next-item"))


@pytest.mark.asyncio
async def test_postgres_migration_refuses_index_left_invalid_by_failed_concurrent_build(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await journal.append(item("one"))
    await journal.append(replace(item("two"), context=replace(context(), thread_id="thread-two")))
    asyncpg = pytest.importorskip("asyncpg")
    async with pool.acquire() as connection:
        await connection.execute(f'DROP INDEX CONCURRENTLY "{schema}".conversation_items_session_read_idx')
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(f'CREATE UNIQUE INDEX CONCURRENTLY conversation_items_session_read_idx ON "{schema}".conversation_items(sequence)')
        with pytest.raises(RuntimeError, match="invalid or incompatible"):
            await apply_migrations(connection, schema=schema)
        await connection.execute(f'DROP INDEX CONCURRENTLY "{schema}".conversation_items_session_read_idx')
        await apply_migrations(connection, schema=schema)


@pytest.mark.asyncio
async def test_postgres_journal_round_trips_display_and_spoken_representations(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    draft = replace(
        item("assistant-1"),
        kind=ConversationItemKind.ASSISTANT_OUTPUT,
        display=DisplayContent(markdown="## 完成\n\n测试通过"),
        spoken=SpokenContent(text="完成，测试通过。", language="zh-CN"),
    )

    appended = await journal.append(draft)
    persisted = (await journal.read(JournalScope.from_context(context())))[0]

    assert persisted == appended.item
    assert persisted.display == draft.display
    assert persisted.spoken == draft.spoken


@pytest.mark.asyncio
async def test_postgres_speech_delivery_round_trips_progress_and_terminal_state(postgres) -> None:
    pool, schema = postgres
    store = PostgresSpeechDeliveryStore(pool, schema=schema)
    await store.start(
        SpeechDeliveryRecord(
            speech_id="speech-1",
            context=context(),
            source_item_id="assistant-1",
            context_policy=SpeechContextPolicy.AUTO,
            interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
        )
    )
    await store.append_text("speech-1", "任务已经完成")
    await store.commit_text("speech-1")
    await store.report_progress(
        "speech-1",
        delivered_text_end=4,
        played_audio_end_us=320_000,
        precision=PlaybackPrecision.SEGMENT,
        completed=False,
    )
    interrupted = await store.cancel("speech-1", reason="barge_in")
    interrupted = await store.report_progress(
        "speech-1",
        delivered_text_end=6,
        played_audio_end_us=480_000,
        precision=PlaybackPrecision.EXACT,
        completed=False,
    )

    assert interrupted.status is SpeechDeliveryStatus.INTERRUPTED
    assert interrupted.delivered_speech_transcript == "任务已经完成"
    assert interrupted.reason == "barge_in"
    assert await store.latest_for_item("assistant-1") == interrupted


@pytest.mark.asyncio
async def test_concurrent_appends_assign_gapless_thread_sequences(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)

    results = await asyncio.gather(*(journal.append(item(f"item-{i}")) for i in range(40)))

    assert sorted(result.item.sequence for result in results) == list(range(1, 41))
    assert await journal.thread_version(JournalScope.from_context(context())) == 40


@pytest.mark.asyncio
async def test_concurrent_identical_retry_is_one_item_without_version_gap(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    draft = item("same-item")

    results = await asyncio.gather(*(journal.append(draft) for _ in range(30)))

    assert sum(result.created for result in results) == 1
    assert {result.item.sequence for result in results} == {1}
    assert await journal.thread_version(JournalScope.from_context(context())) == 1


@pytest.mark.asyncio
async def test_postgres_journal_rejects_changed_id_and_stale_thread_version(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await journal.append(item("item-1"))

    with pytest.raises(JournalConflict):
        await journal.append(item("item-1", "changed"))
    with pytest.raises(ThreadVersionConflict) as captured:
        await journal.append(item("item-2"), expected_thread_version=0)

    assert captured.value.actual == 1


@pytest.mark.asyncio
async def test_postgres_journal_read_is_tenant_and_user_scoped(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await journal.append(item("item-1"))

    cross_tenant = await journal.read(
        JournalScope(tenant_id="tenant-2", user_id="user-1", thread_id="thread-1")
    )
    cross_user = await journal.read(
        JournalScope(tenant_id="tenant-1", user_id="user-2", thread_id="thread-1")
    )

    assert cross_tenant == ()
    assert cross_user == ()


@pytest.mark.asyncio
async def test_global_item_id_cannot_be_reused_in_another_scope(postgres) -> None:
    pool, schema = postgres
    journal = PostgresConversationJournal(pool, schema=schema)
    await journal.append(item("global-item"))
    other_scope = replace(
        item("global-item"),
        context=replace(context(), tenant_id="tenant-2", user_id="user-2"),
    )

    with pytest.raises(JournalConflict):
        await journal.append(other_scope)


@pytest.mark.asyncio
async def test_postgres_agent_event_store_deduplicates_and_persists_cursor(postgres) -> None:
    pool, schema = postgres
    persistence = PostgresPersistence(pool, schema=schema)
    task = (await persistence.agent_tasks.create_or_get(delegation_request())).record
    store = PostgresAgentEventStore(pool, schema=schema)
    event = AgentRunStarted(
        worker_id=task.worker_id,
        event_id="event-1",
        sequence=1,
        occurred_at=utc_now(),
        locator=AgentRunLocator(
            driver_kind="codex",
            backend_session_id="thread-1",
            backend_run_id="turn-1",
        ),
    )

    results = await asyncio.gather(*(store.append(event) for _ in range(20)))

    assert sum(result.created for result in results) == 1
    assert await store.last_sequence(task.worker_id) == 1
    assert [record.event for record in await store.list_events(task.worker_id)] == [event]


@pytest.mark.asyncio
async def test_postgres_agent_event_store_rejects_conflict_and_gap(postgres) -> None:
    pool, schema = postgres
    persistence = PostgresPersistence(pool, schema=schema)
    task = (await persistence.agent_tasks.create_or_get(delegation_request())).record
    store = PostgresAgentEventStore(pool, schema=schema)
    event = AgentRunStarted(
        worker_id=task.worker_id,
        event_id="event-1",
        sequence=1,
        occurred_at=utc_now(),
        locator=AgentRunLocator(
            driver_kind="codex",
            backend_session_id="thread-1",
            backend_run_id="turn-1",
        ),
    )
    await store.append(event)

    with pytest.raises(AgentEventConflict):
        await store.append(
            replace(event, locator=replace(event.locator, backend_run_id="other"))
        )
    with pytest.raises(AgentEventGap) as captured:
        await store.append(replace(event, event_id="event-3", sequence=3))

    assert captured.value.expected == 2
    assert captured.value.actual == 3
