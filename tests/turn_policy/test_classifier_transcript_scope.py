"""Provider contract checks for cumulative decisions from independently sealed chunks."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from server.turn_policy.eot_classifier import EotRequest
from server.turn_policy.plugins.jev_classifier import (
    JevEotClassifier,
    JevSemanticInterruptionClassifier,
)
from server.turn_policy.plugins.llm_eot_classifier import LlmEotClassifier
from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.turn_policy.semantic_input import SemanticInputState
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
    classify_interruption,
)
from tests.turn_policy.test_jev_classifier import Choices

CUMULATIVE_TEXT = "不是北京，是上海。嗯，好。"
CHUNK_TEXT = "嗯，好。"


def request(**kwargs) -> InterruptionRequest:
    return InterruptionRequest(
        transcript=CHUNK_TEXT,
        assistant_text="明天北京晴天",
        generation=1,
        boundary=InterruptionBoundary.SENTENCE_END,
        **kwargs,
    )


def test_cumulative_snapshot_is_optional_and_immutable():
    assert request().cumulative_transcript is None
    frozen = request(cumulative_transcript=CUMULATIVE_TEXT)
    assert frozen.transcript == CHUNK_TEXT
    assert frozen.cumulative_transcript == CUMULATIVE_TEXT
    with pytest.raises(FrozenInstanceError):
        frozen.cumulative_transcript = "新的转写"


@pytest.mark.parametrize("invalid", ["", " \n", 1, [], True])
def test_invalid_cumulative_snapshot_is_rejected(invalid):
    with pytest.raises(ValueError, match="cumulative"):
        request(cumulative_transcript=invalid)


@pytest.mark.parametrize("cumulative", [None, CUMULATIVE_TEXT])
async def test_legacy_classifier_receives_decision_scope(cumulative):
    class Legacy:
        async def classify(self, *, assistant_text, transcript, boundary, generation):
            self.transcript = transcript
            return InterruptionClassification(InterruptionLabel.CORRECTION, 0.9)

    classifier = Legacy()
    result = await classify_interruption(
        classifier, request(cumulative_transcript=cumulative)
    )
    assert classifier.transcript == (cumulative if cumulative is not None else CHUNK_TEXT)
    assert result.label is InterruptionLabel.CORRECTION


async def test_request_classifier_preserves_chunk_and_cumulative_snapshot():
    class Plugin:
        async def classify_request(self, frozen):
            self.request = frozen
            return InterruptionClassification(InterruptionLabel.CORRECTION, 0.9)

    classifier = Plugin()
    frozen = request(cumulative_transcript=CUMULATIVE_TEXT)
    await classify_interruption(classifier, frozen)
    assert classifier.request is frozen
    assert classifier.request.transcript == CHUNK_TEXT
    assert classifier.request.cumulative_transcript == CUMULATIVE_TEXT


@pytest.mark.parametrize("cumulative", [None, CUMULATIVE_TEXT])
async def test_jev_interruption_payload_keeps_both_scopes_without_changing_call_count(cumulative):
    client = Choices("correction")
    await JevSemanticInterruptionClassifier(client).classify_request(
        request(cumulative_transcript=cumulative)
    )
    assert len(client.calls) == 1
    state = client.calls[0]["state"]
    assert state["transcript"] == CHUNK_TEXT
    if cumulative is None:
        assert "cumulative_transcript" not in state
    else:
        assert state["cumulative_transcript"] == CUMULATIVE_TEXT
    instructions = client.calls[0]["instructions"]
    assert "cumulative_transcript" in instructions
    assert "附和不能覆盖" in instructions


class CapturingLlm:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []

    async def complete(self, *, system_prompt, user_text):
        self.calls.append((system_prompt, json.loads(user_text)))
        return self.reply


@pytest.mark.parametrize("cumulative", [None, CUMULATIVE_TEXT])
async def test_llm_interruption_payload_preserves_optional_cumulative_scope(cumulative):
    client = CapturingLlm('{"label":"correction","confidence":0.9}')
    await LlmSemanticInterruptionClassifier(client).classify_request(
        request(cumulative_transcript=cumulative)
    )
    assert len(client.calls) == 1
    prompt, payload = client.calls[0]
    assert payload["transcript"] == CHUNK_TEXT
    if cumulative is None:
        assert "cumulative_transcript" not in payload
    else:
        assert payload["cumulative_transcript"] == CUMULATIVE_TEXT
    assert "cumulative_transcript" in prompt
    assert "附和不能覆盖" in prompt


async def test_jev_eot_prompt_treats_chunk_candidate_as_cumulative_transcript():
    client = Choices("incomplete")
    await JevEotClassifier(client).classify_request(
        EotRequest("我想买票，从北京到", 1, input_state=SemanticInputState(chunk_id="chunk-2"))
    )
    assert client.calls[0]["state"]["transcript"] == "我想买票，从北京到"
    prompt = client.calls[0]["instructions"]
    assert "累计文本" in prompt
    assert "transcript 是独立新块" not in prompt


async def test_llm_eot_prompt_treats_chunk_candidate_as_cumulative_transcript():
    client = CapturingLlm('{"status":"incomplete","confidence":0.9,"wait_ms":100}')
    await LlmEotClassifier(client).classify_request(
        EotRequest("我想买票，从北京到", 1, input_state=SemanticInputState(chunk_id="chunk-2"))
    )
    prompt, payload = client.calls[0]
    assert payload["transcript"] == "我想买票，从北京到"
    assert "cumulative transcript" in prompt
    assert "transcript is an independent new chunk" not in prompt
