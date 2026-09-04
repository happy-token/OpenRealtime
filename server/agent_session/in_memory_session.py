"""Deterministic reference implementation of the Agent Session Protocol.

InMemoryAgentSession/InMemoryDriver are the "EchoLlmClient of the Agent
Session Protocol" — a no-network, test/demo-controllable stand-in, not a
real backend integration. Completion is never wall-clock/network driven:
a test or a demo caller resolves/fails the session explicitly by calling
resolve()/fail() (or push_update() for a progress notification), and
result() simply awaits that.
"""

from __future__ import annotations

import asyncio

from server.agent_session.protocol import DelegationOutcome
from server.core.turn_content import TurnContent


class _Update:
    def __init__(self, text: str) -> None:
        self.text = text


class InMemoryAgentSession:
    def __init__(self) -> None:
        self._content: TurnContent | None = None
        self._update: _Update | None = None
        self._cancelled = False
        self._done = asyncio.Event()
        self._outcome: DelegationOutcome | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def sent_content(self) -> TurnContent | None:
        return self._content

    async def send_turn(self, content: TurnContent) -> None:
        self._content = content

    async def latest_update(self) -> _Update | None:
        return self._update

    async def cancel(self) -> None:
        self._cancelled = True

    async def result(self) -> DelegationOutcome:
        await self._done.wait()
        assert self._outcome is not None
        return self._outcome

    def push_update(self, text: str) -> None:
        self._update = _Update(text)

    def resolve(self, text: str) -> None:
        self._outcome = DelegationOutcome(ok=True, text=text)
        self._done.set()

    def fail(self, reason: str) -> None:
        self._outcome = DelegationOutcome(ok=False, error=reason)
        self._done.set()


class InMemoryDriver:
    """Factory producing fresh, independent InMemoryAgentSession instances."""

    def __init__(self) -> None:
        self.sessions: list[InMemoryAgentSession] = []

    def create_session(self) -> InMemoryAgentSession:
        session = InMemoryAgentSession()
        self.sessions.append(session)
        return session
