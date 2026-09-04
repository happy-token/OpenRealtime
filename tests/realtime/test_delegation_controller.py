from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from server.agent_session.driver_protocol import WorkspaceMode
from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.supervisor import AgentTaskSupervisor
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    DelegationRequest,
)
from server.conversation_journal import ConversationItemKind, JournalScope
from server.core.interaction_context import InteractionContext
from server.persistence.in_memory import InMemoryPersistence
from server.realtime import (
    AgentDelegationRequested,
    AgentDelegationRequestProposed,
    ProjectCommittedItem,
)
from server.realtime.delegation_controller import RealtimeDelegationController


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        response_id="response-1",
    )


class RecordingConversation:
    def __init__(self) -> None:
        self.commands = []
        self.event_queue = asyncio.Queue()

    async def send(self, command) -> None:
        self.commands.append(command)

    async def events(self):
        while True:
            event = await self.event_queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        await self.event_queue.put(None)


def proposed() -> AgentDelegationRequestProposed:
    return AgentDelegationRequestProposed(
        event_id="delegation-proposed-1",
        context=context(),
        conversation_sequence=1,
        occurred_at=datetime.now(UTC),
        response_id="response-1",
        response_sequence=2,
        delegation_request_id="delegation-1",
        instruction="Inspect the project without modifying files",
        agent_name="codex",
    )


def request_from_event(event: AgentDelegationRequestProposed) -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id=event.delegation_request_id,
        selection_plan=AgentSelectionPlan(
            plan_id="voice-runtime-codex",
            version=1,
            primary=AgentCandidate(event.agent_name or "codex"),
        ),
        instruction=event.instruction,
        context=replace(event.context, worker_id=None),
        workspace_root="/workspace",
        workspace_mode=WorkspaceMode.READ_ONLY,
    )


async def test_delegation_controller_commits_before_emitting_authoritative_request() -> None:
    persistence = InMemoryPersistence()
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": InMemoryAgentDriverV2(driver_kind="codex")},
    )
    delegate = RecordingConversation()
    projection = RecordingConversation()
    controller = RealtimeDelegationController(
        context=context(),
        conversation=delegate,
        committed_projection=projection,
        supervisor=supervisor,
        request_factory=request_from_event,
    )
    events = controller.events()

    await delegate.event_queue.put(proposed())

    accepted = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(accepted, AgentDelegationRequested)
    assert accepted.worker_id
    assert accepted.context.worker_id == accepted.worker_id
    assert accepted.instruction == "Inspect the project without modifying files"
    assert len(projection.commands) == 1
    projected = projection.commands[0]
    assert isinstance(projected, ProjectCommittedItem)
    assert projected.item.kind is ConversationItemKind.DELEGATION_REQUESTED
    assert projected.item.context.worker_id == accepted.worker_id
    items = await persistence.journal.read(JournalScope.from_context(context()))
    assert items == (projected.item,)

    await controller.close()
    await supervisor.shutdown()


async def test_replayed_delegation_proposal_does_not_emit_or_spawn_twice() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )
    delegate = RecordingConversation()
    projection = RecordingConversation()
    controller = RealtimeDelegationController(
        context=context(),
        conversation=delegate,
        committed_projection=projection,
        supervisor=supervisor,
        request_factory=request_from_event,
    )
    events = controller.events()

    event = proposed()
    await delegate.event_queue.put(event)
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2),
        AgentDelegationRequested,
    )
    await delegate.event_queue.put(replace(event, event_id="replayed-event"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(projection.commands) == 1
    assert len(await persistence.agent_tasks.list_records()) == 1
    assert driver.start_count == 0
    pending = asyncio.create_task(anext(events))
    try:
        await asyncio.wait_for(asyncio.shield(pending), timeout=0.01)
    except TimeoutError:
        pass
    else:
        raise AssertionError("duplicate proposal emitted a second acceptance")
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)

    await controller.close()
    await supervisor.shutdown()
