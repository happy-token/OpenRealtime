"""Canonical identity and correlation carried across OpenRealtime seams.

The existing runtime still passes a bare generation through several legacy
interfaces.  New v2 seams use :class:`InteractionContext` so identity is not
reconstructed independently by transports, tools, or agent drivers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class InteractionContext:
    tenant_id: str
    user_id: str
    device_id: str
    voice_session_id: str
    thread_id: str
    turn_id: str
    generation: int
    response_id: str | None = None
    call_id: str | None = None
    worker_id: str | None = None
    confirmation_id: str | None = None
    handoff_id: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.tenant_id,
            self.user_id,
            self.device_id,
            self.voice_session_id,
            self.thread_id,
            self.turn_id,
        )
        if any(not value for value in required):
            raise ValueError("InteractionContext identity fields must be non-empty")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")

    def for_worker(self, worker_id: str) -> InteractionContext:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        return replace(self, worker_id=worker_id)
