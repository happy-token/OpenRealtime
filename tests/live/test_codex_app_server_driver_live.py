from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from server.agent_session.driver_protocol import (
    AgentRunTerminal,
    AgentStartRequest,
    WorkspaceLease,
    WorkspaceMode,
    utc_now,
)
from server.agent_session.plugins.codex_app_server import CodexAppServerDriver
from server.core.interaction_context import InteractionContext


CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_CODEX_LIVE") != "1" or not CODEX.exists(),
    reason="set VOICEAGENT_RUN_CODEX_LIVE=1 to call the installed Codex App Server",
)
async def test_installed_codex_app_server_completes_read_only_task() -> None:
    worker_id = "live-codex-worker"
    workspace = str(Path.cwd())
    driver = CodexAppServerDriver(
        command=(str(CODEX), "app-server", "--stdio"),
        ephemeral_threads=True,
        request_timeout_s=60,
    )
    handle = await driver.start(
        AgentStartRequest(
            worker_id=worker_id,
            dispatch_token="live-codex-dispatch",
            instruction="Reply with exactly CODEX_APP_SERVER_DRIVER_OK and do nothing else.",
            context=InteractionContext(
                tenant_id="live",
                user_id="live",
                device_id="local",
                voice_session_id="live-voice",
                thread_id="live-thread",
                turn_id="live-turn",
                generation=1,
                worker_id=worker_id,
            ),
            workspace=WorkspaceLease(
                lease_id="live-lease",
                worker_id=worker_id,
                root=workspace,
                mode=WorkspaceMode.READ_ONLY,
                fencing_token=1,
                expires_at=utc_now() + timedelta(minutes=2),
                allowed_roots=(workspace,),
            ),
            model="gpt-5.4-mini",
        )
    )
    terminal = None
    async for event in driver.events(handle):
        if isinstance(event, AgentRunTerminal):
            terminal = event

    assert terminal is not None
    assert terminal.result == "CODEX_APP_SERVER_DRIVER_OK"
    await driver.close(handle)
