"""Pure, replaceable input association policy; it never controls playback.

Timing is not semantic proof. Unknown relations remain separate input records
with a reference to the previous turn for contextual answering/clarification.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from server.core.turn_content import same_asr_utterance
from server.turn_policy.semantic_interruption import InterruptionLabel, InterruptionVerdict


class InputRelation(StrEnum):
    NEW_TOPIC = "new_topic"
    CORRECTION = "correction"
    SUPPLEMENT = "supplement"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class InputAssociation:
    relation: InputRelation
    related_turn_id: str | None
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.relation, InputRelation) or not self.source.strip():
            raise ValueError("input association requires a typed relation and source")
        if self.relation is InputRelation.NEW_TOPIC:
            if self.related_turn_id is not None:
                raise ValueError("new topic cannot reference a continuation parent")
        elif not self.related_turn_id:
            raise ValueError("related input requires a parent turn identity")

    @property
    def continues_input(self) -> bool:
        return self.relation in {InputRelation.CORRECTION, InputRelation.SUPPLEMENT}


@dataclass(frozen=True, slots=True)
class InputAssociationRequest:
    text: str
    previous_turn_id: str | None
    verdict: InterruptionVerdict | None = None


class InputAssociationPolicy(Protocol):
    def associate(self, request: InputAssociationRequest) -> InputAssociation: ...


@dataclass(frozen=True, slots=True)
class ConservativeInputAssociationPolicy:
    """Explicit discourse markers first, accepted full-snapshot correction second.

    An INTERRUPT verdict decides the floor, not the relationship between inputs.
    A stopped prefix or fallback classification cannot prove final association.
    """

    correction_confidence: float = 0.9

    def __post_init__(self) -> None:
        if not math.isfinite(self.correction_confidence) or not 0 <= self.correction_confidence <= 1:
            raise ValueError("association confidence must be between zero and one")

    def associate(self, request: InputAssociationRequest) -> InputAssociation:
        if not request.text.strip():
            raise ValueError("input association requires non-empty final text")
        if request.previous_turn_id is None:
            return InputAssociation(InputRelation.NEW_TOPIC, None, "first_input")
        text = request.text.strip().casefold()
        if text.startswith(("换个问题", "另一个问题", "新的问题", "重新开始", "new question", "new topic")):
            return InputAssociation(InputRelation.NEW_TOPIC, None, "explicit_new_topic")
        if text.startswith(("不是，", "不是,", "不对，", "不对,", "我说错了", "刚才说错了", "刚才我说错了", "更正一下", "纠正一下")):
            return InputAssociation(InputRelation.CORRECTION, request.previous_turn_id, "explicit_correction")
        if text.startswith(("补充一下", "补充一点", "再补充", "还有明天", "再加上")):
            return InputAssociation(InputRelation.SUPPLEMENT, request.previous_turn_id, "explicit_supplement")
        verdict = request.verdict
        if (verdict is not None and verdict.source != "fallback"
                and verdict.label is InterruptionLabel.CORRECTION
                and verdict.confidence >= self.correction_confidence
                and same_asr_utterance(verdict.candidate.text, request.text)):
            return InputAssociation(InputRelation.CORRECTION, request.previous_turn_id, "accepted_correction")
        return InputAssociation(InputRelation.UNRESOLVED, request.previous_turn_id, "insufficient_evidence")
