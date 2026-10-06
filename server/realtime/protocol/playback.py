"""Provider sentence ranges on one speech's PCM timeline, without permission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from server.core.interaction_context import InteractionContext
from server.core.playback import SentenceSpan as SentenceSpan  # noqa: PLC0414 - public re-export
from server.core.playback import sample_position_us, validate_sample_position
from server.realtime.scope import conversation_scope


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
    played_position_samples: int | None = None
    sample_rate_hz: int | None = None

    def __post_init__(self) -> None:
        validate_sample_position(self.played_position_samples, self.sample_rate_hz)
        if self.position_precision == "sample" and self.played_position_samples is None:
            raise ValueError("sample precision requires the actual PCM clock")
        if self.played_position_samples is not None and self.position_precision != "sample":
            raise ValueError("sample clock requires exact playback precision")
        if self.played_position_samples is not None and self.sample_rate_hz is not None and (
            self.played_audio_end_us != sample_position_us(self.played_position_samples, self.sample_rate_hz)
        ):
            raise ValueError("sample clock and playback microseconds disagree")
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
