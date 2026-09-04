"""Opt-in smoke test for the local FireRedChat ONNX turn detector."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.turn_policy.eot_classifier import EotDecision, EotEvidence, EotRequest
from server.turn_policy.evaluation import load_semantic_eot_cases
from server.turn_policy.plugins.fast_complete_fallback_eot_classifier import (
    FastCompleteFallbackEotClassifier,
)
from server.turn_policy.plugins.fireredchat_eot_provider import (
    FireRedChatEotProvider,
    FireRedChatOnnxModel,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and os.environ.get("FIRERED_MODEL_DIR")),
    reason="requires RUN_LIVE=1 and FIRERED_MODEL_DIR",
)


async def test_fireredchat_chinese_model_distinguishes_clear_endpoint_examples() -> None:
    provider = FireRedChatEotProvider(
        FireRedChatOnnxModel(os.environ["FIRERED_MODEL_DIR"]),
        threshold=0.5,
    )

    incomplete = await provider.evaluate(
        EotRequest(text="我想订一张从北京到", generation=1)
    )
    complete = await provider.evaluate(
        EotRequest(text="帮我查一下明天上海的天气", generation=2)
    )

    assert incomplete.decision is EotDecision.INCOMPLETE
    assert complete.decision is EotDecision.COMPLETE
    assert incomplete.inference_ms < 150
    assert complete.inference_ms < 150


async def test_conservative_fast_complete_has_no_false_cutoffs_on_project_v1() -> None:
    cases = load_semantic_eot_cases(
        Path(__file__).resolve().parents[2]
        / "data"
        / "eot_eval"
        / "zh_semantic_completeness_v1.jsonl"
    )
    expected_by_text = {case.text: case.expected for case in cases}

    class DatasetOracleFallback:
        async def evaluate(self, request: EotRequest) -> EotEvidence:
            return EotEvidence(
                decision=expected_by_text[request.text],
                source="dataset_oracle",
            )

    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=FireRedChatEotProvider(
            FireRedChatOnnxModel(os.environ["FIRERED_MODEL_DIR"]),
            threshold=0.5,
        ),
        fallback_provider=DatasetOracleFallback(),
        fast_complete_threshold=0.5,
    )
    fast_cases = []
    for generation, case in enumerate(cases, start=1):
        result = await classifier.classify_with_context(
            text=case.text,
            generation=generation,
            context=case.context,
        )
        if result.source.startswith("fast_complete:"):
            fast_cases.append(case)

    assert len(fast_cases) >= 5
    assert all(case.expected is EotDecision.COMPLETE for case in fast_cases)
