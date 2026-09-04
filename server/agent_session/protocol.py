"""Agent Session Protocol: contract for delegating a whole turn to an external Agent.

See CONTEXT.md — Agent Session Protocol, Driver, DelegationPolicy, and
ADR-0001/ADR-0006/ADR-0008. Backend-specific launch/auth/workspace details
are supplied by a Driver, never by this protocol itself; see
agent_session/in_memory_session.py for the framework's minimal reference
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.core.turn_content import TurnContent


class SessionUpdate(Protocol):
    """A backend-pushed progress notification, cached for pull-based status queries (ADR-0006)."""

    text: str


@dataclass(frozen=True)
class DelegationOutcome:
    """The final result of a delegated turn — see ADR-0001, ADR-0006.

    Exactly one of `text`/`error` is meaningful, selected by `ok`.
    """

    ok: bool
    text: str | None = None
    error: str | None = None


class AgentSession(Protocol):
    async def send_turn(self, content: TurnContent) -> None: ...
    async def latest_update(self) -> SessionUpdate | None: ...
    async def cancel(self) -> None: ...
    async def result(self) -> DelegationOutcome: ...


class Driver(Protocol):
    """Backend-specific launch/auth/workspace details only — see CONTEXT.md — Driver."""

    def create_session(self) -> AgentSession: ...
