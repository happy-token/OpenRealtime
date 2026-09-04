"""Real `DelegationPolicy` conformer.

See server/brain/delegation_policy.py for the `DelegationPolicy`
Protocol and the framework's never-delegate default.
"""

from __future__ import annotations

from server.core.turn_content import TurnContent


class KeywordDelegationPolicy:
    """Delegates when the turn's text contains one of a fixed set of trigger phrases.

    A minimal demo heuristic (examples/tests only) — not a production-grade
    intent classifier.
    """

    def __init__(
        self,
        triggers: tuple[str, ...],
        target_agent: str,
        *,
        ack_text: str = "Let me look into that.",
    ) -> None:
        self._triggers = triggers
        self._target_agent = target_agent
        self._ack_text = ack_text

    async def choose_agent(self, content: TurnContent) -> str | None:
        if any(trigger in content.text for trigger in self._triggers):
            return self._target_agent
        return None

    def ack_text(self, content: TurnContent) -> str:
        return self._ack_text
