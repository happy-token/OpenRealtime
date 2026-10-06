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
class SemanticInputBudget:
    """Accepted logical-input limits; overflow is rejected, never silently sliced."""

    max_text_bytes: int = 16 * 1024
    max_revisions: int = 2048
    max_chunks: int = 2048
    max_duration_ms: int = 120000
    max_evidence_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in (self.max_text_bytes, self.max_revisions, self.max_chunks,
                             self.max_duration_ms, self.max_evidence_bytes)):
            raise ValueError("semantic input budgets must be positive integers")

    def violation(self, text: str, *, revisions: int, elapsed_ms: float) -> str | None:
        # Bound UTF-8 allocation even if a provider sends an unexpectedly huge snapshot.
        if len(text) > self.max_text_bytes or len(text.encode("utf-8")) > self.max_text_bytes:
            return "input_text_bytes"
        if revisions > self.max_revisions:
            return "input_revisions"
        if elapsed_ms >= self.max_duration_ms:
            return "input_duration"
        return None


@dataclass(frozen=True, slots=True)
class SemanticInputState:
    """Missing observations are unknown, never inferred from a model result."""

    transcript_revision: int | None = None
    boundary: TextBoundary | None = None
    dialogue_state: DialogueState | None = None
    speech_active: bool | None = None
    silence_duration_ms: float | None = None
    audio_timestamp_us: int | None = None
    chunk_id: str | None = None
    chunk_trigger: str | None = None
    previous_chunks: tuple[str, ...] = ()

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
