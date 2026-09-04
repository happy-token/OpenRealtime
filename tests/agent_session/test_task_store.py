from __future__ import annotations

from dataclasses import replace

import pytest

from server.agent_session.driver_protocol import WorkspaceMode
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    DelegationRequest,
    IdempotencyConflict,
    TaskBudget,
    TaskCreateDisposition,
)
from server.agent_session.task_store import InMemoryAgentTaskStore
from server.core.interaction_context import InteractionContext


def make_request(**changes: object) -> DelegationRequest:
    request = DelegationRequest(
        delegation_request_id="request-1",
        selection_plan=AgentSelectionPlan(
            plan_id="default",
            version=1,
            primary=AgentCandidate("codex"),
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
    )
    return replace(request, **changes)


@pytest.mark.asyncio
async def test_strong_idempotency_reuses_one_worker() -> None:
    store = InMemoryAgentTaskStore(worker_id_factory=lambda: "worker-1")

    first = await store.create_or_get(make_request())
    second = await store.create_or_get(make_request())

    assert first.disposition is TaskCreateDisposition.CREATED
    assert second.disposition is TaskCreateDisposition.IDEMPOTENT_REUSE
    assert second.record.worker_id == first.record.worker_id


@pytest.mark.asyncio
async def test_same_request_id_with_changed_budget_is_a_conflict() -> None:
    store = InMemoryAgentTaskStore()
    await store.create_or_get(make_request())

    with pytest.raises(IdempotencyConflict):
        await store.create_or_get(
            make_request(budget=TaskBudget(max_wall_time_s=30, max_tokens=1_000))
        )


@pytest.mark.asyncio
async def test_semantic_dedupe_is_scoped_to_the_same_turn() -> None:
    store = InMemoryAgentTaskStore()
    first = await store.create_or_get(make_request())
    same_turn = await store.create_or_get(make_request(delegation_request_id="request-2"))
    next_turn = await store.create_or_get(
        make_request(
            delegation_request_id="request-3",
            context=replace(make_request().context, turn_id="turn-2"),
        )
    )

    assert same_turn.disposition is TaskCreateDisposition.SEMANTIC_REUSE
    assert same_turn.record.worker_id == first.record.worker_id
    assert next_turn.disposition is TaskCreateDisposition.CREATED
    assert next_turn.record.worker_id != first.record.worker_id


@pytest.mark.asyncio
async def test_semantic_dedupe_ignores_retry_policy_changes() -> None:
    store = InMemoryAgentTaskStore()
    first = await store.create_or_get(make_request())
    retry_with_more_budget = await store.create_or_get(
        make_request(
            delegation_request_id="request-2",
            budget=TaskBudget(max_wall_time_s=600, max_tokens=20_000),
            selection_plan=AgentSelectionPlan(
                plan_id="fallback-plan",
                version=2,
                primary=AgentCandidate("claude"),
                allowed_fallbacks=(AgentCandidate("codex"),),
            ),
        )
    )

    assert retry_with_more_budget.disposition is TaskCreateDisposition.SEMANTIC_REUSE
    assert retry_with_more_budget.record.worker_id == first.record.worker_id


@pytest.mark.asyncio
async def test_force_new_bypasses_semantic_dedupe_but_not_request_idempotency() -> None:
    store = InMemoryAgentTaskStore()
    first = await store.create_or_get(make_request())
    forced = await store.create_or_get(
        make_request(delegation_request_id="request-2", force_new=True)
    )

    assert forced.disposition is TaskCreateDisposition.CREATED
    assert forced.record.worker_id != first.record.worker_id

    later_retry = await store.create_or_get(make_request(delegation_request_id="request-3"))
    assert later_retry.disposition is TaskCreateDisposition.SEMANTIC_REUSE
    assert later_retry.record.worker_id == first.record.worker_id
