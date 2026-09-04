"""Hook Point: sibling mechanism to Event Ledger's Observer.

See CONTEXT.md — Hook Point, and ADR-0002 (dual hook mechanism). A Hook
Point is a named, synchronous, in-line interception point inside a Seam's
default implementation where user middleware may transform or veto the
value in flight. Kept in its own module and object, never merged into
EventLedger, so "did a listener change this value" is never ambiguous —
only Hook Points mutate, Observers never do.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


class Middleware(Protocol):
    def __call__(self, value: str) -> str | None: ...


@dataclass(frozen=True)
class HookPoint:
    name: str
    middlewares: tuple[Middleware, ...] = field(default_factory=tuple)

    def apply(self, value: str) -> str | None:
        """Run each middleware in registration order, feeding each one's
        output to the next. Returns None — vetoing — the moment any
        middleware returns None or raises; later middlewares do not run.
        A raising middleware is logged and treated exactly like an explicit
        veto rather than propagating, so a plugin bug degrades this turn
        the same way every other optional plugin in this framework does,
        instead of crashing the session loop."""
        current = value
        for middleware in self.middlewares:
            started_at = time.monotonic()
            try:
                current = middleware(current)
            except Exception:
                logger.exception(
                    "Hook Point %r middleware %r raised after %.1fms; vetoing",
                    self.name,
                    getattr(middleware, "__name__", repr(middleware)),
                    (time.monotonic() - started_at) * 1000,
                )
                return None
            if current is None:
                return None
        return current
