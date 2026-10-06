"""Immutable speech-local sentence ranges shared by wire and runtime contracts."""

from dataclasses import dataclass


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
