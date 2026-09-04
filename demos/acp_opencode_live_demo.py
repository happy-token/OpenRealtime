"""Manual live smoke test for AcpDriver against a real ACP backend.

Not a pytest test (see docs' live smoke test convention) — run this by hand
against an already-configured `opencode` (or any other ACP-stdio agent)
binary on your PATH:

    uv run python demos/acp_opencode_live_demo.py "write a Chinese
    checkers game as checkers.html"

Prints the Router's Ack immediately, then polls `latest_update()` while
`result()` is still pending, then prints the final `DelegationOutcome` only
once it actually resolves. This is the concrete counter-example to the
qwen-audio-agent live-test finding that motivated this module: OpenRealtime's
Router cannot narrate completion before `session.result()` has actually
resolved, by construction.
"""

from __future__ import annotations

import asyncio
import sys

from server.agent_session.backend_catalog import BackendLaunchConfig, build_drivers
from server.brain.chat_brain import ChatBrain
from server.brain.llm_clients import EchoLlmClient
from server.brain.plugins.keyword_delegation_policy import KeywordDelegationPolicy
from server.brain.router import DelegateToAgent, Router
from server.core.turn_content import TurnContent

_POLL_INTERVAL_S = 1.0
_ACK_TEXT = "Let me have the agent take care of that."
_AGENT_NAME = "opencode"


async def main() -> None:
    task_text = " ".join(sys.argv[1:]) or "write a Chinese checkers game as checkers.html"

    drivers = build_drivers({_AGENT_NAME: BackendLaunchConfig(command=("opencode", "acp"))})
    router = Router(
        ChatBrain(EchoLlmClient()),
        delegation_policy=KeywordDelegationPolicy((task_text,), _AGENT_NAME, ack_text=_ACK_TEXT),
        drivers=drivers,
    )

    decision = await router.decide(TurnContent(text=task_text, generation=1))
    assert isinstance(decision, DelegateToAgent)
    print(f"assistant (ack): {decision.ack_text}")

    result_task = asyncio.ensure_future(decision.session.result())
    while not result_task.done():
        await asyncio.sleep(_POLL_INTERVAL_S)
        update = await decision.session.latest_update()
        if update is not None:
            print(f"assistant (progress): {update.text}")

    outcome = await result_task
    if outcome.ok:
        print(f"assistant (result): {outcome.text}")
    else:
        print(f"assistant (error): {outcome.error}")


if __name__ == "__main__":
    asyncio.run(main())
