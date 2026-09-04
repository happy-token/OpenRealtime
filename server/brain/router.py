"""Router: decides per turn whether to answer via Chat Brain or delegate.

See CONTEXT.md — Router, DelegationPolicy, Driver, BackendCatalog, and
ADR-0001/ADR-0006/ADR-0031. `route()` keeps its original chat-only contract
unchanged (still what `decide()` calls internally for the ChatReply case).
`decide()` is the entry point Kernel uses: with no delegation policy/drivers
registered it always returns a ChatReply, so default behavior is
unaffected. Router holds a `dict[str, Driver]` (typically built via
`agent_session/backend_catalog.py`'s `build_drivers`) since
`DelegationPolicy.choose_agent` names its target directly rather than a
single fixed backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from server.agent_session.protocol import AgentSession, Driver
from server.brain.base import Brain, BrainResponse
from server.brain.delegation_policy import DelegationPolicy, NeverDelegatePolicy
from server.core.turn_content import TurnContent


@dataclass(frozen=True)
class ChatReply:
    response: BrainResponse


@dataclass(frozen=True)
class LocalConversation:
    """Route decision that leaves response generation to Conversation Engine."""


@dataclass(frozen=True)
class DelegateToAgent:
    session: AgentSession
    ack_text: str


RouterDecision = ChatReply | DelegateToAgent
RouterPlan = LocalConversation | DelegateToAgent


class Router:
    def __init__(
        self,
        chat_brain: Brain,
        *,
        delegation_policy: DelegationPolicy | None = None,
        drivers: Mapping[str, Driver] | None = None,
    ) -> None:
        self._chat_brain = chat_brain
        self._delegation_policy = delegation_policy or NeverDelegatePolicy()
        self._drivers = dict(drivers or {})

    async def route(self, content: TurnContent) -> BrainResponse:
        return await self._chat_brain.respond(content)

    async def decide(self, content: TurnContent) -> RouterDecision:
        plan = await self.plan(content)
        if isinstance(plan, DelegateToAgent):
            return plan
        return ChatReply(response=await self.route(content))

    async def plan(self, content: TurnContent) -> RouterPlan:
        """Select local Engine vs. delegation without invoking the legacy Brain."""

        target = await self._delegation_policy.choose_agent(content)
        if target is None:
            return LocalConversation()
        driver = self._drivers.get(target)
        if driver is None:
            raise ValueError(f"DelegationPolicy chose unregistered agent {target!r}")
        session = driver.create_session()
        await session.send_turn(content)
        return DelegateToAgent(session=session, ack_text=self._delegation_policy.ack_text(content))
