"""DelegationPolicy: the plugin interface Router consults to decide chat vs. delegate.

See CONTEXT.md — DelegationPolicy, BackendCatalog, Router, and
ADR-0001/ADR-0008/ADR-0031. `choose_agent` returns the target agent's name
directly (`None` = stay on Chat Brain), deliberately conflating "should we
delegate" with "to whom" into one decision (ADR-0031). Default
(unregistered) behavior never delegates, reproducing v1's original
chat-only Router exactly. The real `KeywordDelegationPolicy` conformer
(a minimal demo heuristic for examples/tests, not a production-grade
intent classifier) lives in brain/plugins/keyword_delegation_policy.py.
"""

from __future__ import annotations

from typing import Protocol

from server.core.turn_content import TurnContent


class DelegationPolicy(Protocol):
    async def choose_agent(self, content: TurnContent) -> str | None: ...
    def ack_text(self, content: TurnContent) -> str: ...


class NeverDelegatePolicy:
    """The framework default: chat-only, matches v1's original Router behavior."""

    async def choose_agent(self, content: TurnContent) -> str | None:
        return None

    def ack_text(self, content: TurnContent) -> str:
        raise AssertionError("NeverDelegatePolicy never delegates, so ack_text is never used")
