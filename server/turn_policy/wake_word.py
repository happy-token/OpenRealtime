"""WakeWordDetector: an optional Hook Point gating τ1 only.

See CONTEXT.md — Wake Word, and ADR-0005. Independent of and stacks with
AddresseeClassifier (both must allow τ1 to fire); does not gate τ11, which
stays AddresseeClassifier-only per ADR-0005's explicit scoping. Unregistered
(default) behavior allows entry to LISTEN unconditionally — a Wake Word gate
is opt-in, not a default requirement.
"""

from __future__ import annotations

from typing import Protocol


class WakeWordDetector(Protocol):
    async def is_wake_event(self, *, generation: int) -> bool: ...


class NoWakeWordGating:
    async def is_wake_event(self, *, generation: int) -> bool:
        return True
