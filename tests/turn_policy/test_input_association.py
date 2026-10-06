from dataclasses import replace

import pytest

from server.turn_policy.input_association import (
    ConservativeInputAssociationPolicy,
    InputAssociation,
    InputAssociationRequest,
    InputRelation,
)
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionVerdict,
)


@pytest.mark.parametrize(("text", "relation"), [
    ("换个问题，日期是多少", InputRelation.NEW_TOPIC),
    ("不是，上海", InputRelation.CORRECTION),
    ("刚才我说错了，是上海", InputRelation.CORRECTION),
    ("补充一下，带孩子", InputRelation.SUPPLEMENT),
    ("还有明天", InputRelation.SUPPLEMENT),
    ("帮我查日期", InputRelation.UNRESOLVED),
    ("不是所有酒店都合适", InputRelation.UNRESOLVED),
])
def test_explicit_evidence_and_unknown_preserve_relationship(text, relation):
    result = ConservativeInputAssociationPolicy().associate(InputAssociationRequest(text, "parent"))
    assert result.relation is relation
    assert result.related_turn_id == (None if relation is InputRelation.NEW_TOPIC else "parent")


def test_first_input_has_no_invented_parent():
    result = ConservativeInputAssociationPolicy().associate(InputAssociationRequest("不是，上海", None))
    assert result == InputAssociation(InputRelation.NEW_TOPIC, None, "first_input")


@pytest.mark.parametrize("change", ["full", "prefix", "fallback", "interrupt", "confidence", "rewrite"])
def test_only_accepted_full_snapshot_correction_proves_association(change):
    verdict = InterruptionVerdict(
        InterruptionCandidate("上海才对", 1, 1, InterruptionBoundary.PARTIAL),
        InterruptionClassification(InterruptionLabel.CORRECTION, 1), "model",
    )
    text = "上海才对。"
    if change == "prefix":
        text += "另外日期是多少"
    elif change == "rewrite":
        text = "天气不错"
    elif change == "fallback":
        verdict = replace(verdict, source="fallback")
    elif change == "interrupt":
        verdict = replace(verdict, classification=InterruptionClassification(InterruptionLabel.INTERRUPT, 1))
    elif change == "confidence":
        verdict = replace(verdict, classification=InterruptionClassification(InterruptionLabel.CORRECTION, .5))
    result = ConservativeInputAssociationPolicy().associate(InputAssociationRequest(text, "parent", verdict))
    assert result.relation is (InputRelation.CORRECTION if change == "full" else InputRelation.UNRESOLVED)


@pytest.mark.parametrize("confidence", [-.1, 1.1, float("nan"), float("inf")])
def test_invalid_confidence_fails_at_configuration(confidence):
    with pytest.raises(ValueError):
        ConservativeInputAssociationPolicy(correction_confidence=confidence)


@pytest.mark.parametrize(("relation", "parent"), [
    (InputRelation.CORRECTION, None), (InputRelation.SUPPLEMENT, ""),
    (InputRelation.UNRESOLVED, None), (InputRelation.NEW_TOPIC, "old"),
])
def test_invalid_parent_contract_is_rejected(relation, parent):
    with pytest.raises(ValueError):
        InputAssociation(relation, parent, "test")
