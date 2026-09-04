from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentRunHandle,
    AgentStartRequest,
    WorkspaceMode,
)
from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.supervisor import (
    AgentSelectionError,
    AgentTaskSupervisor,
    FallbackConfirmationRequired,
)
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    AgentTaskPhase,
    ConfirmationRule,
    DelegationRequest,
    TaskCreateDisposition,
)
from server.agent_session.task_store import InMemoryAgentTaskStore
from server.core.interaction_context import InteractionContext
from server.persistence.in_memory import InMemoryPersistence


class AmbiguousStartDriver(InMemoryAgentDriverV2):
    async def capabilities(self) -> AgentCapabilityDescriptor:
        descriptor = await super().capabilities()
        return replace(
            descriptor,
            capabilities=descriptor.capabilities - {AgentCapability.IDEMPOTENT_START},
        )

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        await super().start(request)
        raise ConnectionError("connection dropped after dispatch")


def make_request(
    *,
    request_id: str = "request-1",
    plan: AgentSelectionPlan | None = None,
    force_new: bool = False,
) -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id=request_id,
        selection_plan=plan
        or AgentSelectionPlan(
            plan_id="default",
            version=1,
            primary=AgentCandidate("codex"),
            required_capabilities=frozenset({AgentCapability.EVENT_STREAM}),
        ),
        instruction="Inspect the project",
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
async def test_concurrent_duplicate_submissions_start_exactly_one_run() -> None:
    store = InMemoryAgentTaskStore()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": driver},
    )

    submissions = await asyncio.gather(*(supervisor.submit(make_request()) for _ in range(100)))

    assert len({submission.record.worker_id for submission in submissions}) == 1
    assert driver.start_count == 0
    assert (
        sum(
            submission.create_result.disposition is TaskCreateDisposition.CREATED
            for submission in submissions
        )
        == 1
    )
    await supervisor.dispatch_once(owner="dispatcher")
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_terminal_driver_event_is_reflected_in_task_store() -> None:
    store = InMemoryAgentTaskStore()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": driver},
    )
    submission = await supervisor.submit(make_request())
    await supervisor.dispatch_once(owner="dispatcher")

    await driver.complete(submission.record.worker_id, "done")
    for _ in range(20):
        current = await supervisor.get(submission.record.worker_id)
        if current is not None and current.phase.terminal:
            break
        await asyncio.sleep(0)

    assert current is not None
    assert current.phase is AgentTaskPhase.SUCCEEDED
    assert current.result == "done"
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_fallback_is_explicit_and_can_require_confirmation() -> None:
    fallback = InMemoryAgentDriverV2(driver_kind="codex")
    store = InMemoryAgentTaskStore()
    plan = AgentSelectionPlan(
        plan_id="fallback",
        version=1,
        primary=AgentCandidate("claude"),
        allowed_fallbacks=(AgentCandidate("codex"),),
        confirmation_on_fallback=ConfirmationRule.REQUIRE,
    )
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": fallback},
    )

    with pytest.raises(FallbackConfirmationRequired):
        await supervisor.submit(make_request(plan=plan))

    assert fallback.start_count == 0
    records = await store.list_records()
    assert records[0].phase is AgentTaskPhase.FAILED
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_fallback_reason_must_be_explicitly_allowed() -> None:
    fallback = InMemoryAgentDriverV2(driver_kind="codex")
    plan = AgentSelectionPlan(
        plan_id="no-fallback-reasons",
        version=1,
        primary=AgentCandidate("claude"),
        allowed_fallbacks=(AgentCandidate("codex"),),
        confirmation_on_fallback=ConfirmationRule.NOTIFY,
        fallback_reason_allowlist=frozenset(),
    )
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(),
        drivers={"codex": fallback},
    )

    with pytest.raises(AgentSelectionError):
        await supervisor.submit(make_request(plan=plan))

    assert fallback.start_count == 0
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_unavailable_plan_fails_without_hidden_backend_selection() -> None:
    store = InMemoryAgentTaskStore()
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={},
    )

    with pytest.raises(AgentSelectionError):
        await supervisor.submit(make_request())

    records = await store.list_records()
    assert len(records) == 1
    assert records[0].phase is AgentTaskPhase.FAILED
    assert records[0].selected_agent is None
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_force_new_creates_an_independent_worker() -> None:
    store = InMemoryAgentTaskStore()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": driver},
    )

    first = await supervisor.submit(make_request())
    second = await supervisor.submit(replace(make_request(request_id="request-2"), force_new=True))

    assert first.record.worker_id != second.record.worker_id
    await supervisor.dispatch_once(owner="dispatcher")
    assert driver.start_count == 2
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_ambiguous_start_keeps_dedupe_guard_and_does_not_respawn() -> None:
    store = InMemoryAgentTaskStore()
    driver = AmbiguousStartDriver(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": driver},
    )

    first = await supervisor.submit(make_request())
    await supervisor.dispatch_once(owner="dispatcher", retry_delay_seconds=0)
    duplicate = await supervisor.submit(make_request(request_id="request-2"))
    current = await supervisor.get(first.record.worker_id)

    assert current is not None
    assert current.phase is AgentTaskPhase.UNKNOWN
    assert duplicate.record.worker_id == first.record.worker_id
    assert duplicate.create_result.disposition is TaskCreateDisposition.SEMANTIC_REUSE
    assert driver.start_count == 1

    after_cancel = await supervisor.cancel(first.record.worker_id, "cancel uncertain run")
    assert after_cancel.phase is AgentTaskPhase.UNKNOWN

    third = await supervisor.submit(make_request(request_id="request-3"))
    assert third.record.worker_id == first.record.worker_id
    assert driver.start_count == 1
    await supervisor.shutdown()
