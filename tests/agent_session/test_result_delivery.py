from __future__ import annotations

import asyncio

from server.agent_session.driver_protocol import WorkspaceMode
from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.result_delivery import AgentResultDeliveryWorker
from server.agent_session.supervisor import AgentTaskSupervisor
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    DelegationRequest,
)
from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.conversation_journal import ConversationItemKind, JournalScope
from server.core.interaction_context import InteractionContext
from server.persistence.in_memory import InMemoryPersistence
from server.persistence.outbox import OutboxStatus
from server.realtime import (
    InMemoryRealtimeConversation,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemProjected,
    JournaledRealtimeConversation,
    ResponseRequested,
)
from server.realtime.registry import ActiveRealtimeConversations


def context(*, generation: int = 1) -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id=f"turn-{generation}",
        generation=generation,
    )


def request() -> DelegationRequest:
    return DelegationRequest(
        delegation_request_id="request-1",
        selection_plan=AgentSelectionPlan(
            plan_id="codex-first",
            version=1,
            primary=AgentCandidate("codex"),
        ),
        instruction="Inspect the project",
        context=context(),
        workspace_root="/workspace",
        workspace_mode=WorkspaceMode.READ_ONLY,
    )


async def test_committed_agent_result_is_projected_then_delivered_when_idle() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(request())
    await supervisor.dispatch_once(owner="dispatcher")
    await driver.complete(submission.record.worker_id, "检查完成，测试通过。")
    for _ in range(30):
        record = await supervisor.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0)

    active_context = context(generation=2)
    engine = InMemoryRealtimeConversation(context=active_context)
    conversation = JournaledRealtimeConversation(
        context=active_context,
        journal=persistence.journal,
        engine_conversation=engine,
    )
    conversations = ActiveRealtimeConversations()
    conversations.register(context=active_context, conversation=conversation)
    delivery = AgentResultDeliveryWorker(
        persistence=persistence,
        conversations=conversations,
    )
    events = conversation.events()

    results = await delivery.deliver_once(owner="result-delivery")

    assert len(results) == 1
    assert results[0].delivered is True
    emitted = []
    while not emitted or not isinstance(emitted[-1], ResponseRequested):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.5))
    assert any(isinstance(event, ItemProjected) for event in emitted)
    assert any(isinstance(event, ItemDeliveryQueued) for event in emitted)
    assert any(isinstance(event, ItemDeliveryStarted) for event in emitted)
    projected_sequence = max(
        event.thread_sequence for event in emitted if isinstance(event, ItemProjected)
    )
    requested = emitted[-1]
    assert requested.minimum_thread_sequence == projected_sequence
    assert requested.context.generation == 2
    assert requested.context.worker_id == submission.record.worker_id

    claimed_again = await persistence.outbox.claim(
        owner="another-worker",
        limit=10,
        lease_seconds=30,
    )
    assert all(message.status is not OutboxStatus.DELIVERED for message in claimed_again)
    items = await persistence.journal.read(JournalScope.from_context(active_context))
    terminal = next(item for item in items if item.kind is ConversationItemKind.DELEGATION_RESULT)
    assert terminal.sequence == projected_sequence

    await conversation.close()
    await supervisor.shutdown()


async def test_result_delivery_remains_pending_while_voice_session_is_offline() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(persistence=persistence, drivers={"codex": driver})
    submission = await supervisor.submit(request())
    await supervisor.dispatch_once(owner="dispatcher")
    await driver.complete(submission.record.worker_id, "检查完成。")
    for _ in range(30):
        record = await supervisor.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0)

    resumed_context = context(generation=2)
    engine = InMemoryRealtimeConversation(context=resumed_context)
    resumed = JournaledRealtimeConversation(
        context=resumed_context,
        journal=persistence.journal,
        engine_conversation=engine,
    )
    conversations = ActiveRealtimeConversations()
    conversations.register(context=resumed_context, conversation=resumed)
    conversations.suspend(context=resumed_context, conversation=resumed)
    delivery = AgentResultDeliveryWorker(
        persistence=persistence,
        conversations=conversations,
        retry_delay_seconds=0,
    )

    results = await delivery.deliver_once(owner="result-delivery")

    assert len(results) == 1
    assert results[0].delivered is False
    assert "not connected" in (results[0].error or "")
    assert results[0].message.status is OutboxStatus.PENDING

    conversations.resume(context=resumed_context, conversation=resumed)

    replayed = await delivery.deliver_once(owner="result-delivery-after-reconnect")

    assert len(replayed) == 1
    assert replayed[0].delivered is True
    assert replayed[0].message.status is OutboxStatus.DELIVERED
    resumed_events = resumed.events()
    emitted = []
    while not emitted or not isinstance(emitted[-1], ResponseRequested):
        emitted.append(await asyncio.wait_for(anext(resumed_events), timeout=0.5))
    assert any(isinstance(event, ItemProjected) for event in emitted)
    assert isinstance(emitted[-1], ResponseRequested)

    await resumed.close()
    await supervisor.shutdown()


async def test_application_runtime_delivers_agent_result_to_active_realtime_session() -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=runtime.persistence,
        drivers={"codex": driver},
    )
    submission = await supervisor.submit(request())
    await supervisor.dispatch_once(owner="dispatcher")

    active_context = context(generation=2)
    engine = InMemoryRealtimeConversation(context=active_context)
    conversation = JournaledRealtimeConversation(
        context=active_context,
        journal=runtime.journal,
        engine_conversation=engine,
    )
    runtime.active_realtime_conversations.register(
        context=active_context,
        conversation=conversation,
    )
    events = conversation.events()

    await driver.complete(submission.record.worker_id, "后台任务已完成。")

    emitted = []
    while not emitted or not isinstance(emitted[-1], ResponseRequested):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.5))
    assert any(isinstance(event, ItemProjected) for event in emitted)
    assert isinstance(emitted[-1], ResponseRequested)

    await conversation.close()
    await supervisor.shutdown()
    await runtime.close()
