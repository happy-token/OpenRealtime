"""Brain: the unit that decides what to say next in a turn. See CONTEXT.md — Brain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.core.turn_content import TurnContent


@dataclass(frozen=True)
class ActionOutput:
    """Non-verbal action/gesture instructions alongside speech. See CONTEXT.md — Action Output."""

    emotion: str | None = None
    gesture: str | None = None


@dataclass(frozen=True)
class BrainResponse:
    text: str
    generation: int
    action: ActionOutput | None = None


class Brain(Protocol):
    async def respond(self, content: TurnContent) -> BrainResponse: ...
