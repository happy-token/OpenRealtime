"""Immutable, optional observations shared by semantic decision plugins."""

import math
from dataclasses import dataclass
from enum import StrEnum

from server.turn_policy.states import DialogueState


class TextBoundary(StrEnum):
    PARTIAL = "partial"
    SENTENCE_END = "sentence_end"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class SemanticInputState:
    """Missing observations are unknown, never inferred from a model result."""

    transcript_revision: int | None = None
    boundary: TextBoundary | None = None
    dialogue_state: DialogueState | None = None
    speech_active: bool | None = None
    silence_duration_ms: float | None = None
    audio_timestamp_us: int | None = None

    def __post_init__(self) -> None:
        for value in (self.transcript_revision, self.audio_timestamp_us):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(
                    "semantic input revisions and timestamps must be non-negative integers"
                )
        if self.boundary is not None and not isinstance(self.boundary, TextBoundary):
            raise ValueError("semantic input boundary is invalid")
        if self.dialogue_state is not None and not isinstance(self.dialogue_state, DialogueState):
            raise ValueError("semantic input dialogue state is invalid")
        if self.speech_active is not None and not isinstance(self.speech_active, bool):
            raise ValueError("semantic input speech activity must be boolean")
        if self.silence_duration_ms is not None and (
            isinstance(self.silence_duration_ms, bool)
            or not math.isfinite(self.silence_duration_ms)
            or self.silence_duration_ms < 0
        ):
            raise ValueError("semantic input silence duration must be finite and non-negative")
