"""Event Ledger: fan-out point for read-only Observers.

See CONTEXT.md — Observer, and ADR-0002 (dual hook mechanism). Observers are
async and cannot mutate the pipeline; a failing Observer is logged, never
allowed to interrupt the conversation loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LedgerEvent:
    name: str
    generation: int
    payload: dict[str, Any] = field(default_factory=dict)


class Observer(Protocol):
    async def __call__(self, event: LedgerEvent) -> None: ...


class EventLedger:
    def __init__(self) -> None:
        self._observers: list[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        self._observers.append(observer)

    async def emit(self, name: str, *, generation: int, **payload: Any) -> None:
        if not self._observers:
            return
        event = LedgerEvent(name=name, generation=generation, payload=payload)
        results = await asyncio.gather(
            *(observer(event) for observer in self._observers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.exception("Event Ledger observer raised", exc_info=result)
