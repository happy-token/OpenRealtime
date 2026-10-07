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
    input_relation_unresolved: bool = False
    context_projection_digest: str | None = None
    context_repair: bool = False

    @property
    def model_text(self) -> str:
        """Current utterance plus bounded Journal context for model input."""

        text = self.text if not self.conversation_context else (
            "最近对话上下文：\n"
            f"{self.conversation_context}\n\n"
            f"当前用户输入：{self.text}"
        )
        if self.input_relation_unresolved:
            text = (
                "本轮输入与上一轮的关联尚未确认。请结合上下文理解原意；"
                "不要擅自把它合并为纠正或补充。如果独立回答所需的信息完整，可以直接回答；"
                "否则先简短询问它是在补充上一轮还是提出新问题，确认前不要执行依赖该关联的操作。\n\n"
                + text
            )
        if self.context_repair:
            text = (
                "这是依据最新已确认播放内容对原回复的续答修正，并非新的用户操作授权。"
                "不要重复用户已经听到的内容。原回复的工具或委派可能已执行或仍在运行；"
                "只引用上下文中已确认的结果，未知执行状态须明确说明。"
                "本次仅生成续答文本，不得再次请求任何工具或委派；需要新操作时先向用户说明。\n\n"
                + text
            )
        return text
