"""Generation counter and lease mechanism.

See CONTEXT.md — Generation, and ADR-0001 (two-layer external agent integration).
"""

from __future__ import annotations

from dataclasses import dataclass


class GenerationCounter:
    """Tracks the current conversation generation for one session.

    Advances whenever a new user turn supersedes prior in-flight work (e.g. a
    fresh user turn arrives while a delegation from an earlier turn is still
    running).
    """

    def __init__(self) -> None:
        self._value = 0

    @property
    def current(self) -> int:
        return self._value

    def advance(self) -> int:
        self._value += 1
        return self._value

    def lease(self) -> GenerationLease:
        """Snapshot the current generation for later staleness checks."""
        return GenerationLease(generation=self._value, counter=self)


@dataclass(frozen=True)
class GenerationLease:
    """A held generation number, checked against the counter's current value.

    Used to gate injection of a delegated result (success or error) — see
    ADR-0006. If the counter has since advanced, the lease is stale and the
    result must not be spoken.
    """

    generation: int
    counter: GenerationCounter

    def is_current(self) -> bool:
        return self.counter.current == self.generation
