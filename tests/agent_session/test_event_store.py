from __future__ import annotations

from dataclasses import replace

import pytest

from server.agent_session.driver_protocol import (
    AgentRunLocator,
    AgentRunStarted,
    AgentRunWaiting,
    utc_now,
)
from server.agent_session.event_store import (
    AgentEventConflict,
    AgentEventGap,
    InMemoryAgentEventStore,
)


def started(*, event_id: str = "event-1", sequence: int = 1) -> AgentRunStarted:
    return AgentRunStarted(
        worker_id="worker-1",
        event_id=event_id,
        sequence=sequence,
        occurred_at=utc_now(),
        locator=AgentRunLocator(
            driver_kind="codex",
            backend_session_id="thread-1",
            backend_run_id="turn-1",
        ),
    )


@pytest.mark.asyncio
async def test_event_store_deduplicates_identical_callback_and_tracks_cursor() -> None:
    store = InMemoryAgentEventStore()
    event = started()

    first = await store.append(event)
    duplicate = await store.append(event)

    assert first.created is True
    assert duplicate.created is False
    assert await store.last_sequence("worker-1") == 1
    assert await store.list_events("worker-1") == (first.record,)


@pytest.mark.asyncio
async def test_event_store_rejects_changed_identity_and_sequence_gaps() -> None:
    store = InMemoryAgentEventStore()
    event = started()
    await store.append(event)

    with pytest.raises(AgentEventConflict):
        await store.append(replace(event, locator=replace(event.locator, backend_run_id="other")))
    with pytest.raises(AgentEventGap) as captured:
        await store.append(
            AgentRunWaiting(
                worker_id="worker-1",
                event_id="event-3",
                sequence=3,
                occurred_at=utc_now(),
                locator=event.locator,
                reason="input",
            )
        )

    assert captured.value.expected == 2
    assert captured.value.actual == 3
