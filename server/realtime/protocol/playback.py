"""Provider sentence ranges on one speech's PCM timeline, without permission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from server.core.interaction_context import InteractionContext
from server.realtime.scope import conversation_scope


@dataclass(frozen=True, slots=True, kw_only=True)
class SentenceSpan:
    sentence_id: str
    text: str
    text_start: int
    text_end: int
    audio_start_us: int
    audio_end_us: int

    def __post_init__(self) -> None:
        if not isinstance(self.sentence_id, str) or not self.sentence_id:
            raise ValueError("sentence identity must be non-empty")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("sentence text must be non-empty")
        if any(
            type(value) is not int or not 0 <= value <= 2**53 - 1
            for value in (
                self.text_start,
                self.text_end,
                self.audio_start_us,
                self.audio_end_us,
            )
        ):
            raise ValueError("sentence positions must be non-negative integers")
        if (
            self.text_end - self.text_start != len(self.text)
            or self.audio_end_us <= self.audio_start_us
        ):
            raise ValueError(
                "sentence ranges must match original code-point text and positive audio span"
            )


def sentence_identity(
    context: InteractionContext, speech_id: str, text: str, text_start: int
) -> str:
    """Repeated text has separate offset identity; timings never grant permission."""
    if not speech_id:
        raise ValueError("sentence requires its speech identity")
    key = (
        *conversation_scope(context),
        context.turn_id,
        context.generation,
        speech_id,
        text_start,
        text,
    )
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()
