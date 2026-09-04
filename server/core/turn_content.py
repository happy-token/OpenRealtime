"""Turn Content: the multimodal bundle passed to the Brain Gateway/Router.

See CONTEXT.md — Turn Content, Voiceprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VoiceprintResult = Literal["match", "no_match", "unavailable", "adaptive"]
_TERMINAL_SENTENCE_PUNCTUATION = frozenset("。！？.!?")


def canonical_asr_utterance(text: str) -> str:
    """Ignore only trailing sentence punctuation added by a final ASR revision."""

    normalized = text.strip()
    while normalized and normalized[-1] in _TERMINAL_SENTENCE_PUNCTUATION:
        normalized = normalized[:-1].rstrip()
    return normalized


def same_asr_utterance(left: str, right: str) -> bool:
    """Return true when two ASR revisions differ only by terminal punctuation."""

    left_canonical = canonical_asr_utterance(left)
    return bool(left_canonical) and left_canonical == canonical_asr_utterance(right)


@dataclass(frozen=True)
class AudioMetadata:
    duration_ms: int
    sample_rate_hz: int


@dataclass(frozen=True)
class TurnContent:
    """Text (ASR transcript), audio metadata, and optional vision/voiceprint metadata.

    Voiceprint is attached here as informational metadata only (ADR-0005) — it
    never gates a Turn Policy transition.
    """

    text: str
    generation: int
    audio: AudioMetadata | None = None
    vision_text: str | None = None
    voiceprint: VoiceprintResult | None = None
    conversation_context: str | None = None

    @property
    def model_text(self) -> str:
        """Current utterance plus bounded Journal context for model input."""

        if not self.conversation_context:
            return self.text
        return (
            "最近对话上下文：\n"
            f"{self.conversation_context}\n\n"
            f"当前用户输入：{self.text}"
        )
