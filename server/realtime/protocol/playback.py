"""Provider sentence ranges on one speech's PCM timeline, without permission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyPlayback:
    """Latest server-received playback fact, never a delivery permission."""

    output_epoch: str | None
    speech_id: str
    played_audio_end_us: int
    confirmed_text_end: int
    observed_at_ns: int
    position_precision: Literal["sample", "unknown"] = "unknown"
    current_sentence: SentenceSpan | None = None
    terminal: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.speech_id, str) or not self.speech_id:
            raise ValueError("playback requires its speech identity")
        if self.output_epoch is not None and (
            not isinstance(self.output_epoch, str) or not self.output_epoch
        ):
            raise ValueError("playback epoch must be non-empty when provided")
        if (
            any(
                type(value) is not int or value < 0
                for value in (
                    self.played_audio_end_us,
                    self.confirmed_text_end,
                    self.observed_at_ns,
                )
            )
            or self.observed_at_ns == 0
            or type(self.terminal) is not bool
        ):
            raise ValueError("playback positions and observation clock must be valid")
        if self.position_precision not in {"sample", "unknown"} or (
            self.position_precision == "sample" and self.output_epoch is None
        ):
            raise ValueError("invalid playback position precision")
        if self.current_sentence is not None and (
            self.position_precision != "sample"
            or self.output_epoch is None
            or self.terminal
            or not self.current_sentence.audio_start_us
            < self.played_audio_end_us
            < self.current_sentence.audio_end_us
            or self.confirmed_text_end > self.current_sentence.text_end
        ):
            raise ValueError(
                "current sentence requires non-terminal exact playback within its range"
            )
