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
from server.agent_session.supervisor import AGENT_RESULT_MESSAGE_TYPE, AgentTaskSupervisor
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    AgentTaskPhase,
    DelegationRequest,
    TaskBudget,
)
from server.conversation_journal import ConversationItemKind, JournalScope, TextContent
from server.core.interaction_context import InteractionContext
from server.persistence.in_memory import InMemoryPersistence
from server.persistence.outbox import OutboxStatus


class LostAckOnceDriver(InMemoryAgentDriverV2):
    def __init__(self) -> None:
        super().__init__(driver_kind="idempotent")
        self._drop_next_ack = True

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        handle = await super().start(request)
        if self._drop_next_ack:
            self._drop_next_ack = False
            raise ConnectionError("start succeeded but its acknowledgement was lost")
        return handle


class NonIdempotentAmbiguousDriver(InMemoryAgentDriverV2):
    async def capabilities(self) -> AgentCapabilityDescriptor:
        descriptor = await super().capabilities()
        return replace(
            descriptor,
            capabilities=descriptor.capabilities - {AgentCapability.IDEMPOTENT_START},
        )

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        await super().start(request)
        raise ConnectionError("start outcome is ambiguous")


class NonResumableDriver(InMemoryAgentDriverV2):
    def __init__(self) -> None:
        super().__init__(driver_kind="non-resumable")
        self.resume_count = 0

    async def capabilities(self) -> AgentCapabilityDescriptor:
        descriptor = await super().capabilities()
        return replace(
            descriptor,
            capabilities=descriptor.capabilities
            - {AgentCapability.RESUME, AgentCapability.STATUS_LOOKUP},
        )

    async def resume(
        self,
        locator,
        *,
        worker_id,
        dispatch_token,
        after_sequence,
    ):
        self.resume_count += 1
        return await super().resume(
            locator,
            worker_id=worker_id,
            dispatch_token=dispatch_token,
            after_sequence=after_sequence,
        )


def make_request(request_id: str = "request-1") -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id=request_id,
        selection_plan=AgentSelectionPlan(
            plan_id="codex-first",
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


@pytest.mark.asyncio
async def test_submit_commits_task_and_outbox_before_starting_driver() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})

    submission = await supervisor.submit(make_request())

    assert submission.record.phase is AgentTaskPhase.STARTING
    assert submission.dispatch_message is not None
    assert submission.dispatch_message.status is OutboxStatus.PENDING
    assert driver.start_count == 0
    journal_items = await persistence.journal.read(
        JournalScope.from_context(submission.record.context)
    )
    assert len(journal_items) == 1
    assert journal_items[0].kind is ConversationItemKind.DELEGATION_REQUESTED
    assert journal_items[0].context.worker_id == submission.record.worker_id

    dispatched = await supervisor.dispatch_once(owner="dispatcher-1")

    assert len(dispatched) == 1
    assert dispatched[0].started
    assert dispatched[0].message.status is OutboxStatus.DELIVERED
    assert dispatched[0].record.phase is AgentTaskPhase.RUNNING
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_submission_retry_does_not_duplicate_delegation_intent() -> None:
    persistence = InMemoryPersistence()
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": InMemoryAgentDriverV2(driver_kind="codex")},
    )

    first = await supervisor.submit(make_request())
    retried = await supervisor.submit(make_request())
    items = await persistence.journal.read(JournalScope.from_context(first.record.context))

    assert retried.record.worker_id == first.record.worker_id
    assert [item.kind for item in items] == [ConversationItemKind.DELEGATION_REQUESTED]
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_concurrent_dispatchers_start_one_backend_run() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    await supervisor.submit(make_request())

    first, second = await asyncio.gather(
        supervisor.dispatch_once(owner="dispatcher-1"),
        supervisor.dispatch_once(owner="dispatcher-2"),
    )

    assert len((*first, *second)) == 1
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_retry_reuses_existing_task_before_rechecking_driver_health() -> None:
    persistence = InMemoryPersistence()
    accepting = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": InMemoryAgentDriverV2(driver_kind="codex")},
    )
    original = await accepting.submit(make_request())
    unavailable = AgentTaskSupervisor(persistence=persistence, drivers={})

    strong_retry = await unavailable.submit(make_request())
    semantic_retry = await unavailable.submit(make_request("request-2"))

    assert strong_retry.record.worker_id == original.record.worker_id
    assert semantic_retry.record.worker_id == original.record.worker_id
    await accepting.shutdown()
    await unavailable.shutdown()


@pytest.mark.asyncio
async def test_idempotent_driver_recovers_lost_start_ack_without_duplicate_spawn() -> None:
    persistence = InMemoryPersistence()
    driver = LostAckOnceDriver()
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())

    first = await supervisor.dispatch_once(owner="dispatcher-1", retry_delay_seconds=0)
    after_first = await supervisor.get(submission.record.worker_id)
    second = await supervisor.dispatch_once(owner="dispatcher-2", retry_delay_seconds=0)

    assert first[0].message.status is OutboxStatus.PENDING
    assert after_first is not None
    assert after_first.phase is AgentTaskPhase.STARTING
    assert after_first.dispatch_attempt_count == 1
    assert second[0].record.phase is AgentTaskPhase.RUNNING
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_non_idempotent_ambiguous_start_becomes_unknown_and_never_respawns() -> None:
    persistence = InMemoryPersistence()
    driver = NonIdempotentAmbiguousDriver(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())

    first = await supervisor.dispatch_once(owner="dispatcher-1", retry_delay_seconds=0)
    second = await supervisor.dispatch_once(owner="dispatcher-2", retry_delay_seconds=0)
    record = await supervisor.get(submission.record.worker_id)

    assert first[0].message.status is OutboxStatus.DEAD
    assert second == ()
    assert record is not None
    assert record.phase is AgentTaskPhase.UNKNOWN
    assert record.dispatch_attempt_count == 1
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_expired_claim_before_start_is_safe_to_retry() -> None:
    persistence = InMemoryPersistence()
    driver = NonIdempotentAmbiguousDriver(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())
    claimed = await persistence.outbox.claim(
        owner="crashed-before-start",
        limit=1,
        lease_seconds=0.001,
        message_types=frozenset({"agent.dispatch.requested.v1"}),
    )
    assert claimed
    await asyncio.sleep(0.01)

    dispatched = await supervisor.dispatch_once(owner="recovery")
    record = await supervisor.get(submission.record.worker_id)

    assert dispatched
    assert record is not None
    assert record.dispatch_attempt_count == 1
    assert driver.start_count == 1
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_recovery_never_repeats_non_idempotent_fenced_start_attempt() -> None:
    persistence = InMemoryPersistence()
    driver = NonIdempotentAmbiguousDriver(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())
    attempting = await persistence.agent_tasks.begin_dispatch(
        submission.record.worker_id,
        expected_revision=submission.record.revision,
    )

    dispatched = await supervisor.dispatch_once(owner="recovery")
    record = await supervisor.get(submission.record.worker_id)

    assert attempting.dispatch_attempt_count == 1
    assert dispatched[0].message.status is OutboxStatus.DEAD
    assert record is not None
    assert record.phase is AgentTaskPhase.UNKNOWN
    assert driver.start_count == 0
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_dispatch_does_not_start_after_workspace_lease_budget_expires() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    request = replace(make_request(), budget=TaskBudget(max_wall_time_s=0.001))
    submission = await supervisor.submit(request)
    await asyncio.sleep(0.01)

    dispatched = await supervisor.dispatch_once(owner="dispatcher")
    record = await supervisor.get(submission.record.worker_id)

    assert dispatched[0].message.status is OutboxStatus.DEAD
    assert record is not None
    assert record.phase is AgentTaskPhase.TIMED_OUT
    assert driver.start_count == 0
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_cancel_before_dispatch_consumes_outbox_without_starting_backend() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())

    cancelled = await supervisor.cancel(submission.record.worker_id, "user cancelled")
    dispatched = await supervisor.dispatch_once(owner="dispatcher")

    assert cancelled.phase is AgentTaskPhase.CANCELLED
    assert dispatched[0].message.status is OutboxStatus.DELIVERED
    assert driver.start_count == 0
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_restart_recovery_reattaches_without_starting_another_run() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    first_process = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )
    submission = await first_process.submit(make_request())
    await first_process.dispatch_once(owner="dispatcher-1")
    await first_process.shutdown()

    recovered_process = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )
    recovered = await recovered_process.recover_active()
    await driver.complete(submission.record.worker_id, "recovered")
    for _ in range(20):
        record = await recovered_process.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0)

    assert recovered == (submission.record.worker_id,)
    assert record is not None
    assert record.phase is AgentTaskPhase.SUCCEEDED
    assert record.result == "recovered"
    assert driver.start_count == 1
    await recovered_process.shutdown()


@pytest.mark.asyncio
async def test_restart_does_not_resume_or_respawn_backend_without_safe_capabilities() -> None:
    persistence = InMemoryPersistence()
    driver = NonResumableDriver()
    first = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await first.submit(make_request())
    await first.dispatch_once(owner="dispatcher")
    await first.shutdown()

    recovered = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    workers = await recovered.recover_active()
    record = await recovered.get(submission.record.worker_id)

    assert workers == ()
    assert record is not None
    assert record.phase is AgentTaskPhase.UNKNOWN
    assert record.error is not None
    assert "cannot safely resume/status" in record.error
    assert driver.resume_count == 0
    assert driver.start_count == 1
    await recovered.shutdown()


@pytest.mark.asyncio
async def test_terminal_event_is_persisted_with_journal_result_and_delivery_outbox() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(make_request())
    await supervisor.dispatch_once(owner="dispatcher")

    await driver.complete(submission.record.worker_id, "done")
    for _ in range(30):
        record = await supervisor.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0)

    events = await persistence.agent_events.list_events(submission.record.worker_id)
    items = await persistence.journal.read(JournalScope.from_context(submission.record.context))
    deliveries = await persistence.outbox.claim(
        owner="delivery",
        limit=10,
        lease_seconds=30,
        message_types=frozenset({AGENT_RESULT_MESSAGE_TYPE}),
    )

    assert [event.event.sequence for event in events] == [1, 2]
    assert [item.kind for item in items] == [
        ConversationItemKind.DELEGATION_REQUESTED,
        ConversationItemKind.DELEGATION_RESULT,
    ]
    assert any(
        isinstance(part, TextContent) and part.text == "done"
        for part in items[-1].content
    )
    assert len(deliveries) == 1
    assert deliveries[0].aggregate_id == submission.record.worker_id
    assert deliveries[0].payload["thread_sequence"] == items[-1].sequence
    await supervisor.shutdown()


class NoReplayDriver(InMemoryAgentDriverV2):
    async def capabilities(self) -> AgentCapabilityDescriptor:
        descriptor = await super().capabilities()
        return replace(
            descriptor,
            capabilities=descriptor.capabilities - {AgentCapability.EVENT_REPLAY},
        )


@pytest.mark.asyncio
async def test_recovery_reconciles_terminal_status_without_replaying_or_respawning() -> None:
    persistence = InMemoryPersistence()
    driver = NoReplayDriver(driver_kind="codex")
    first = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await first.submit(make_request())
    await first.dispatch_once(owner="dispatcher")
    for _ in range(20):
        if await persistence.agent_events.last_sequence(submission.record.worker_id) == 1:
            break
        await asyncio.sleep(0)
    await first.shutdown()
    await driver.complete(submission.record.worker_id, "finished offline")

    recovered = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    workers = await recovered.recover_active()
    record = await recovered.get(submission.record.worker_id)

    assert workers == (submission.record.worker_id,)
    assert record is not None
    assert record.phase is AgentTaskPhase.SUCCEEDED
    assert record.result == "finished offline"
    assert driver.start_count == 1
    assert await persistence.agent_events.last_sequence(submission.record.worker_id) == 2
    await recovered.shutdown()
