from __future__ import annotations

import asyncio

import pytest

from server.observability.telemetry import (
    DebugLogEntry,
    InMemoryDebugLogStore,
    RuntimeDebugLog,
)


class BlockingDebugLogStore(InMemoryDebugLogStore):
    def __init__(self) -> None:
        super().__init__()
        self.write_started = asyncio.Event()
        self.release_write = asyncio.Event()

    async def append_batch(self, entries) -> None:
        self.write_started.set()
        await self.release_write.wait()
        await super().append_batch(entries)


async def test_session_debug_log_assigns_increasing_sequence_and_queries_in_order() -> None:
    store = InMemoryDebugLogStore()
    runtime = RuntimeDebugLog(store, batch_size=2)
    await runtime.start()
    session = runtime.bind("voice-1")

    session.log("eot", "decision", "EOT=complete via llm_eot_classifier", generation=1)
    session.log("interruption", "decision", "label=stop source=rule", generation=1)
    session.log("turn", "terminal", "outcome=ok", generation=1)

    await runtime.flush()
    timeline = await store.session_timeline("voice-1")

    assert [entry.sequence for entry in timeline] == [1, 2, 3]
    assert [entry.stage for entry in timeline] == ["eot", "interruption", "turn"]
    assert timeline[0].summary == "EOT=complete via llm_eot_classifier"

    await runtime.close()


async def test_session_timeline_only_returns_entries_for_requested_session() -> None:
    store = InMemoryDebugLogStore()
    runtime = RuntimeDebugLog(store, batch_size=1)
    await runtime.start()

    runtime.bind("voice-a").log("eot", "decision", "a-decision")
    runtime.bind("voice-b").log("eot", "decision", "b-decision")
    await runtime.flush()

    timeline = await store.session_timeline("voice-a")

    assert len(timeline) == 1
    assert timeline[0].voice_session_id == "voice-a"
    assert timeline[0].summary == "a-decision"

    await runtime.close()


async def test_debug_log_entry_rejects_empty_identity_fields() -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValueError):
        DebugLogEntry(
            event_id="event-1",
            voice_session_id="",
            sequence=1,
            stage="eot",
            event="decision",
            summary="x",
            occurred_at=datetime.now(UTC),
        )


async def test_debug_log_queue_is_bounded_when_storage_stalls() -> None:
    store = BlockingDebugLogStore()
    runtime = RuntimeDebugLog(store, batch_size=1, max_queue_size=1)
    await runtime.start()
    session = runtime.bind("voice-overload")

    session.log("eot", "decision", "first")
    await store.write_started.wait()
    session.log("eot", "decision", "queued")
    session.log("eot", "decision", "dropped")

    assert runtime.pending_entries == 1
    assert runtime.dropped_entries == 1

    store.release_write.set()
    await runtime.close()


async def test_debug_log_detail_is_redacted_like_telemetry_attributes() -> None:
    store = InMemoryDebugLogStore()
    runtime = RuntimeDebugLog(store, batch_size=1)
    await runtime.start()
    session = runtime.bind("voice-1")

    session.log(
        "eot",
        "decision",
        "EOT=complete",
        detail={"text": "this should become a length", "confidence": 0.9},
    )
    await runtime.flush()
    timeline = await store.session_timeline("voice-1")

    assert "text" not in timeline[0].detail
    assert timeline[0].detail["text_length"] == len("this should become a length")
    assert timeline[0].detail["confidence"] == 0.9

    await runtime.close()


async def test_postgres_debug_log_deletion_preserves_other_sessions() -> None:
    import os
    from pathlib import Path
    from uuid import uuid4

    if os.environ.get("RUN_ADMIN_POSTGRES_TEST") != "1":
        pytest.skip("requires explicit PostgreSQL integration opt-in")
    import asyncpg
    from server.persistence.postgres.debug_log import PostgresDebugLogStore

    schema = f"debug_test_{uuid4().hex}"
    connection = await asyncpg.connect(os.environ["VOICEAGENT_POSTGRES_DSN"])
    runtime = None
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        migration = Path("server/persistence/postgres/migrations/0032_session_debug_log.sql").read_text()
        await connection.execute(migration.replace("__VOICEAGENT_SCHEMA__", schema))
        store = PostgresDebugLogStore(connection, schema=schema)
        runtime = RuntimeDebugLog(store)
        await runtime.start()
        runtime.bind("delete").log("turn", "decision", "delete me")
        runtime.bind("keep").log("turn", "decision", "keep me")
        assert await runtime.delete_sessions(["delete", "delete"]) == 1
        assert not await store.session_timeline("delete")
        assert len(await store.session_timeline("keep")) == 1
        assert await runtime.delete_sessions(["delete"]) == 0
    finally:
        if runtime is not None:
            await runtime.close()
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()
