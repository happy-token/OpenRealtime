from __future__ import annotations

import json

import pytest

from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
)


class StubLlmClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, str]] = []

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_text": user_text})
        return self.reply


async def test_classifier_uses_strict_six_label_contract_and_playback_context() -> None:
    client = StubLlmClient('{"label":"correction","confidence":0.93}')
    classifier = LlmSemanticInterruptionClassifier(client)

    result = await classifier.classify(
        assistant_text="明天北京晴天",
        transcript="不是北京，是上海",
        boundary=InterruptionBoundary.PARTIAL,
        generation=9,
    )

    assert result == InterruptionClassification(InterruptionLabel.CORRECTION, 0.93)
    assert len(client.calls) == 1
    payload = json.loads(client.calls[0]["user_text"])
    assert payload == {
        "assistant_playback": "明天北京晴天",
        "transcript": "不是北京，是上海",
        "boundary": "partial",
    }
    assert "只输出 JSON" in client.calls[0]["system_prompt"]


async def test_classifier_rejects_non_json_or_extra_fields() -> None:
    bad = LlmSemanticInterruptionClassifier(StubLlmClient("interrupt 0.9"))
    with pytest.raises(ValueError):
        await bad.classify(
            assistant_text="answer",
            transcript="new task",
            boundary=InterruptionBoundary.SENTENCE_END,
            generation=1,
        )

    extra = LlmSemanticInterruptionClassifier(
        StubLlmClient('{"label":"interrupt","confidence":0.9,"reason":"x"}')
    )
    with pytest.raises(ValueError):
        await extra.classify(
            assistant_text="answer",
            transcript="new task",
            boundary=InterruptionBoundary.SENTENCE_END,
            generation=1,
        )
