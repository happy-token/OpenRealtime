"""Turn Content: the multimodal bundle passed to the Brain Gateway/Router.

See CONTEXT.md — Turn Content, Voiceprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from server.core.playback import CurrentSentencePermit, SentenceSpan, sample_position_us

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


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionalSentenceHandoff:
    """Private generation hypothesis; never a recorded playback fact."""

    permit: CurrentSentencePermit
    sentence: SentenceSpan
    expected_context: str | None
    expected_projection_digest: str

    def __post_init__(self) -> None:
        if (self.sentence.sentence_id != self.permit.sentence_id
            or self.sentence.audio_start_us != sample_position_us(self.permit.audio_start_samples, self.permit.sample_rate_hz)
            or self.sentence.audio_end_us != sample_position_us(self.permit.audio_end_samples, self.permit.sample_rate_hz)
            or self.permit.confirmed_text_end > self.sentence.text_start
            or len(self.expected_projection_digest) != 64):
            raise ValueError("conditional handoff must match the exact permitted sentence")
        context = self.expected_context or ""
        if len(context) > 64 * 1024 or len(context.encode("utf-8")) > 64 * 1024:
            raise ValueError("conditional handoff context exceeds its private budget")


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
    conditional_handoff: ConditionalSentenceHandoff | None = None

    @property
    def model_text(self) -> str:
        """Current utterance plus bounded Journal context for model input."""

        context = (self.conditional_handoff.expected_context if self.conditional_handoff is not None
            else self.conversation_context)
        text = self.text if not context else (
            "最近对话上下文：\n"
            f"{context}\n\n"
            f"当前用户输入：{self.text}"
        )
        if self.conditional_handoff is not None:
            text = (
                "这是私有的句末衔接条件计划，尚未确认许可句完整播放。"
                "下方上下文仅针对许可句完整播放后的情形；请只为这个条件准备续答，"
                "不要重复预计已经播完的句子。条件未成立时本候选将作废，不得将计划当作已听事实。\n\n"
                + text
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


def same_response_basis(left: TurnContent, right: TurnContent) -> bool:
    """Formal actual projection must exactly discharge any private hypothesis."""
    left_plan, right_plan = left.conditional_handoff, right.conditional_handoff
    if left_plan is not None and right_plan is not None and left_plan != right_plan:
        return False
    left_context = left_plan.expected_context if left_plan is not None else left.conversation_context
    right_context = right_plan.expected_context if right_plan is not None else right.conversation_context
    left_digest = left_plan.expected_projection_digest if left_plan is not None else left.context_projection_digest
    right_digest = right_plan.expected_projection_digest if right_plan is not None else right.context_projection_digest
    return (left.generation == right.generation and same_asr_utterance(left.text, right.text)
        and left_context == right_context and left_digest == right_digest
        and left.input_relation_unresolved == right.input_relation_unresolved
        and left.context_repair == right.context_repair and left.vision_text == right.vision_text
        and left.audio == right.audio and left.voiceprint == right.voiceprint)
