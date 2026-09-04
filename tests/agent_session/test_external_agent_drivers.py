from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentMessageDelta,
    AgentRunPhase,
    AgentRunTerminal,
    AgentStartRequest,
    WorkspaceLease,
    WorkspaceMode,
    utc_now,
)
from server.agent_session.plugins.acp_driver import AcpDriver
from server.agent_session.plugins.claude_stream_json import ClaudeStreamJsonDriver
from server.agent_session.plugins.hermes_acp import HermesAcpDriver
from server.core.interaction_context import InteractionContext


_ACP_FIXTURE = Path(__file__).parents[1] / "fixtures" / "fake_acp_agent.py"
_CLAUDE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "fake_claude_stream.py"


def start_request(worker_id: str = "worker-1") -> AgentStartRequest:
    workspace_root = str(Path.cwd())
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    ).for_worker(worker_id)
    return AgentStartRequest(
        worker_id=worker_id,
        dispatch_token=f"dispatch-{worker_id}",
        instruction="inspect project",
        context=context,
        workspace=WorkspaceLease(
            lease_id=f"lease-{worker_id}",
            worker_id=worker_id,
            root=workspace_root,
            mode=WorkspaceMode.READ_ONLY,
            fencing_token=1,
            expires_at=utc_now() + timedelta(minutes=1),
            allowed_roots=(workspace_root,),
        ),
    )


@pytest.mark.asyncio
async def test_hermes_acp_adapter_emits_universal_events_without_unsafe_capabilities() -> None:
    legacy = AcpDriver(
        command=(sys.executable, str(_ACP_FIXTURE)),
        env={"ACP_FIXTURE_SCENARIO": "success"},
    )
    driver = HermesAcpDriver(acp=legacy, poll_interval_seconds=0.001)

    descriptor = await driver.capabilities()
    handle = await driver.start(start_request())
    events = [event async for event in driver.events(handle)]

    assert AgentCapability.IDEMPOTENT_START not in descriptor.capabilities
    assert AgentCapability.RESUME not in descriptor.capabilities
    assert AgentCapability.WORKSPACE_ISOLATION not in descriptor.capabilities
    assert isinstance(events[-1], AgentRunTerminal)
    assert events[-1].phase is AgentRunPhase.SUCCEEDED
    assert events[-1].result == "Working on it."
    await driver.close(handle)


@pytest.mark.asyncio
async def test_claude_stream_json_adapter_maps_deltas_usage_and_terminal_result() -> None:
    driver = ClaudeStreamJsonDriver(
        command=(sys.executable, str(_CLAUDE_FIXTURE)),
    )

    descriptor = await driver.capabilities()
    handle = await driver.start(start_request())
    events = [event async for event in driver.events(handle)]

    assert AgentCapability.IDEMPOTENT_START not in descriptor.capabilities
    assert AgentCapability.RESUME not in descriptor.capabilities
    assert AgentCapability.WORKSPACE_ISOLATION not in descriptor.capabilities
    assert "".join(
        event.text for event in events if isinstance(event, AgentMessageDelta)
    ) == "Working done."
    assert isinstance(events[-1], AgentRunTerminal)
    assert events[-1].phase is AgentRunPhase.SUCCEEDED
    assert events[-1].result == "Working done."
    await driver.close(handle)


@pytest.mark.asyncio
async def test_claude_cancel_targets_exact_worker_process() -> None:
    driver = ClaudeStreamJsonDriver(
        command=(sys.executable, str(_CLAUDE_FIXTURE)),
        env={**os.environ, "CLAUDE_FIXTURE_SCENARIO": "slow"},
    )
    handle = await driver.start(start_request())

    cancelled = await driver.cancel(handle, "user cancelled")
    events = [event async for event in driver.events(handle)]

    assert cancelled.stopped is True
    assert cancelled.phase is AgentRunPhase.CANCELLED
    assert isinstance(events[-1], AgentRunTerminal)
    assert events[-1].phase is AgentRunPhase.CANCELLED
    await driver.close(handle)
