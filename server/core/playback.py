"""Immutable speech-local sentence ranges shared by wire and runtime contracts."""

from dataclasses import dataclass

from server.core.interaction_context import InteractionContext


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


def sample_position_us(position: int, sample_rate_hz: int) -> int:
    """Round one cumulative PCM clock, using integer ties-to-even arithmetic."""
    whole, remainder = divmod(position * 1_000_000, sample_rate_hz)
    return whole + int(
        2 * remainder > sample_rate_hz or (2 * remainder == sample_rate_hz and whole % 2 == 1)
    )


def validate_sample_position(position: int | None, sample_rate_hz: int | None) -> None:
    """Legacy positions have neither field; exact positions require both."""
    if position is None and sample_rate_hz is None:
        return
    if (
        type(position) is not int
        or not 0 <= position <= 2**53 - 1
        or type(sample_rate_hz) is not int
        or not 0 < sample_rate_hz <= 384000
    ):
        raise ValueError("exact playback requires a safe sample position and valid rate")


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentSentencePermit:
    """Actor authority for one already-started sentence, never new delivery."""

    permit_id: str
    context: InteractionContext
    input_id: str
    input_version: int
    response_id: str
    reply_version: int
    output_epoch: str
    speech_id: str
    sentence_id: str
    audio_start_samples: int
    audio_end_samples: int
    sample_rate_hz: int
    trigger_input_id: str
    trigger_transcript_revision: int
    issued_at_ns: int
    expires_at_ns: int
    confirmed_text_end: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.permit_id, self.input_id, self.response_id, self.output_epoch,
            self.speech_id, self.sentence_id, self.trigger_input_id)):
            raise ValueError("sentence permit identities must be non-empty")
        validate_sample_position(self.audio_start_samples, self.sample_rate_hz)
        validate_sample_position(self.audio_end_samples, self.sample_rate_hz)
        if (self.audio_start_samples >= self.audio_end_samples
            or self.speech_id not in {self.response_id, f"response:{self.response_id}"}
            or any(type(value) is not int or not 0 < value <= 2**53 - 1 for value in (
                self.input_version, self.reply_version, self.trigger_transcript_revision))
            or any(type(value) is not int or value < 0 for value in (
                self.issued_at_ns, self.expires_at_ns, self.confirmed_text_end))
            or not 0 < self.expires_at_ns - self.issued_at_ns <= 5_000_000_000):
            raise ValueError("sentence permit requires a finite valid version and sample range")
