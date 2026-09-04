"""Unit tests for the real ACP `Driver` conformer (acp_driver.py), run
against tests/fixtures/fake_acp_agent.py — a real subprocess, not a mock —
so `SubprocessAcpTransport` and the JSON-RPC/NDJSON wire handling are
exercised for real without needing any vendor CLI installed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from server.agent_session.plugins.acp_driver import AcpAgentSession, AcpDriver
from server.core.turn_content import TurnContent

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fake_acp_agent.py"


def _driver(scenario: str) -> AcpDriver:
    return AcpDriver(
        command=(sys.executable, str(_FIXTURE_PATH)),
        env={"ACP_FIXTURE_SCENARIO": scenario},
    )


async def _poll(predicate, *, attempts: int = 200, interval: float = 0.005):
    for _ in range(attempts):
        value = predicate()
        if value is not None:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("condition never became true")


async def _await_session_id(session: AcpAgentSession) -> None:
    await _poll(lambda: session._session_id)


async def test_send_turn_dispatches_prompt_and_result_blocks_until_done():
    session = _driver("success").create_session()

    await session.send_turn(TurnContent(text="write checkers.html", generation=1))
    result_task = asyncio.ensure_future(session.result())
    await asyncio.sleep(0)
    assert not result_task.done()

    outcome = await result_task
    assert outcome.ok is True
    assert outcome.text == "Working on it."


async def test_latest_update_reflects_streamed_chunks_before_completion():
    # `streaming_gate` blocks the fake agent on a real, unbounded stdin read
    # until it sees a `session/cancel` notification — a deterministic gate,
    # not a timing race — so the "before completion" window is observable
    # for as long as the test needs.
    session = _driver("streaming_gate").create_session()

    await session.send_turn(TurnContent(text="write checkers.html", generation=1))

    update = await _poll(lambda: None if session._done.is_set() else session._latest_text)
    assert update == "Working"
    assert not session._done.is_set()
    seen = await session.latest_update()
    assert seen is not None
    assert seen.text == "Working"

    await session.cancel()  # releases the fixture's gate; not a real cancellation here
    outcome = await session.result()
    assert outcome.ok is True
    assert outcome.text == "Working on it."


async def test_cancel_sends_notification():
    session = _driver("cancel_probe").create_session()
    await session.send_turn(TurnContent(text="write checkers.html", generation=1))
    await _await_session_id(session)

    await session.cancel()

    outcome = await session.result()
    assert outcome.ok is False
    assert outcome.error == "ACP turn ended with stopReason='cancelled'"
    update = await session.latest_update()
    assert update is not None
    assert update.text == "cancelled-received"


async def test_permission_request_rejected_by_default():
    session = _driver("permission_gate").create_session()

    await session.send_turn(TurnContent(text="write checkers.html", generation=1))
    outcome = await session.result()

    assert outcome.ok is True
    assert outcome.text == "Workingapproved:reject-once"


async def test_error_response_surfaces_as_delegation_outcome_error():
    session = _driver("error").create_session()

    await session.send_turn(TurnContent(text="write checkers.html", generation=1))
    outcome = await session.result()

    assert outcome.ok is False
    assert outcome.error is not None
    assert "backend exploded" in outcome.error


async def test_subprocess_crash_surfaces_as_error():
    session = _driver("crash").create_session()

    await session.send_turn(TurnContent(text="write checkers.html", generation=1))
    outcome = await session.result()

    assert outcome.ok is False
    assert outcome.error is not None
    assert "exited unexpectedly" in outcome.error
