from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentMessageDelta,
    AgentPlanUpdated,
    AgentRunPhase,
    AgentRunStarted,
    AgentRunTerminal,
    AgentStartRequest,
    AgentUsageUpdated,
    WorkspaceLease,
    WorkspaceMode,
    utc_now,
)
from server.agent_session.plugins.codex_app_server import CodexAppServerDriver
from server.agent_session.supervisor import AgentTaskSupervisor
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    AgentTaskPhase,
    DelegationRequest,
)
from server.agent_session.task_store import InMemoryAgentTaskStore
from server.core.interaction_context import InteractionContext
from server.persistence.in_memory import InMemoryPersistence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "fake_codex_app_server.py"


def start_request(worker_id: str = "worker-1") -> AgentStartRequest:
    return AgentStartRequest(
        worker_id=worker_id,
        dispatch_token=f"dispatch-{worker_id}",
        instruction="Reply with the fixture marker",
        context=InteractionContext(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
            turn_id="voice-turn-1",
            generation=1,
            worker_id=worker_id,
        ),
        workspace=WorkspaceLease(
            lease_id=f"lease-{worker_id}",
            worker_id=worker_id,
            root="/tmp",
            mode=WorkspaceMode.READ_ONLY,
            fencing_token=1,
            expires_at=utc_now() + timedelta(minutes=1),
            allowed_roots=("/tmp",),
        ),
        model="test-model",
    )


@pytest.mark.asyncio
async def test_codex_driver_translates_stream_and_terminal_result() -> None:
    driver = CodexAppServerDriver(command=(sys.executable, str(FIXTURE)), ephemeral_threads=True)
    descriptor = await driver.capabilities()
    handle = await driver.start(start_request())

    events = [event async for event in driver.events(handle)]
    snapshot = await driver.status(handle)

    assert isinstance(events[0], AgentRunStarted)
    assert any(isinstance(event, AgentMessageDelta) for event in events)
    assert any(isinstance(event, AgentPlanUpdated) for event in events)
    assert any(isinstance(event, AgentUsageUpdated) for event in events)
    assert isinstance(events[-1], AgentRunTerminal)
    assert events[-1].phase is AgentRunPhase.SUCCEEDED
    assert events[-1].result == "FAKE_CODEX_OK"
    assert snapshot.phase is AgentRunPhase.SUCCEEDED
    assert snapshot.result == "FAKE_CODEX_OK"
    assert AgentCapability.EVENT_REPLAY not in descriptor.capabilities
    await driver.close(handle)


@pytest.mark.asyncio
async def test_codex_driver_uses_one_isolated_thread_per_worker() -> None:
    driver = CodexAppServerDriver(command=(sys.executable, str(FIXTURE)))

    first = await driver.start(start_request("worker-1"))
    second = await driver.start(start_request("worker-2"))

    assert first.locator.backend_session_id != second.locator.backend_session_id
    assert first.locator.backend_run_id != second.locator.backend_run_id
    await driver.close(first)
    await driver.close(second)


@pytest.mark.asyncio
async def test_codex_driver_reuses_dispatch_token_in_process() -> None:
    driver = CodexAppServerDriver(command=(sys.executable, str(FIXTURE)))
    request = start_request()

    first = await driver.start(request)
    second = await driver.start(request)

    assert second == first
    await driver.close(first)


@pytest.mark.asyncio
async def test_codex_driver_interrupt_reaches_terminal_cancelled_event() -> None:
    driver = CodexAppServerDriver(command=(sys.executable, str(FIXTURE)))
    request = start_request()
    request = AgentStartRequest(
        worker_id=request.worker_id,
        dispatch_token=request.dispatch_token,
        instruction="WAIT_FOR_CANCEL",
        context=request.context,
        workspace=request.workspace,
    )
    handle = await driver.start(request)

    cancel_result = await driver.cancel(handle, "voice user cancelled")
    events = [event async for event in driver.events(handle)]

    assert cancel_result.requested
    assert isinstance(events[-1], AgentRunTerminal)
    assert events[-1].phase is AgentRunPhase.CANCELLED
    await driver.close(handle)


@pytest.mark.asyncio
async def test_codex_driver_runs_behind_the_universal_supervisor() -> None:
    store = InMemoryAgentTaskStore()
    driver = CodexAppServerDriver(command=(sys.executable, str(FIXTURE)), ephemeral_threads=True)
    supervisor = AgentTaskSupervisor(
        persistence=InMemoryPersistence(agent_tasks=store),
        drivers={"codex": driver},
    )
    base = start_request()
    request = DelegationRequest(
        delegation_request_id="supervised-codex-request",
        selection_plan=AgentSelectionPlan(
            plan_id="codex-first",
            version=1,
            primary=AgentCandidate("codex", model="test-model"),
        ),
        instruction=base.instruction,
        context=base.context.__class__(
            tenant_id=base.context.tenant_id,
            user_id=base.context.user_id,
            device_id=base.context.device_id,
            voice_session_id=base.context.voice_session_id,
            thread_id=base.context.thread_id,
            turn_id=base.context.turn_id,
            generation=base.context.generation,
        ),
        workspace_root=base.workspace.root,
        workspace_mode=base.workspace.mode,
    )

    submission = await supervisor.submit(request)
    await supervisor.dispatch_once(owner="dispatcher")
    for _ in range(50):
        record = await supervisor.get(submission.record.worker_id)
        if record is not None and record.phase.terminal:
            break
        await asyncio.sleep(0)

    assert record is not None
    assert record.phase is AgentTaskPhase.SUCCEEDED
    assert record.result == "FAKE_CODEX_OK"
    await supervisor.shutdown()
