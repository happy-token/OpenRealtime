"""Immutable transport observations; these do not grant playback permission."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from server.core.interaction_context import InteractionContext
from server.transport.frames import AssistantSpeechCancelledFrame


@dataclass(frozen=True, slots=True)
class OutputStopObservation:
    request: AssistantSpeechCancelledFrame
    target_context: InteractionContext | None
    phase: Literal["requested", "receipt", "handoff_ready", "handoff_failed"]
    state: Literal["STOP_REQUESTED", "STOP_CONFIRMED", "STOP_UNKNOWN"]
    reason: str | None
    receipt_outcome: Literal["queue_stopped", "unknown", "stale"] | None
    played_position_samples: int | None
    requested_at: datetime
    received_at: datetime | None
    occurred_at: datetime
    requested_ns: int
    received_ns: int | None
    monotonic_ns: int
    timeout_ms: float
