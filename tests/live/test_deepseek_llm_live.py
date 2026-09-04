"""Opt-in live smoke test for the direct DeepSeek voice fast-path LLM."""

from __future__ import annotations

import os

import pytest

from server.brain.plugins.openai_compatible_llm_client import (
    OpenAiCompatibleLlmClient,
)
from server.turn_policy.eot_classifier import EotDecision
from server.turn_policy.plugins.llm_eot_classifier import (
    EOT_RESPONSE_SCHEMA,
    LlmEotClassifier,
)
from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionLabel,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and os.environ.get("DEEPSEEK_API_KEY")),
    reason="requires RUN_LIVE=1 and a real DEEPSEEK_API_KEY",
)


async def test_deepseek_v4_flash_streams_a_non_thinking_voice_reply() -> None:
    client = OpenAiCompatibleLlmClient(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        disable_thinking=True,
        api_style="responses",
        timeout_s=30.0,
    )

    chunks = [
        chunk
        async for chunk in client.stream(
            system_prompt="你是简洁的语音助手，只回答一句中文。",
            user_text="请回复：DeepSeek 语音链路正常。",
        )
    ]

    assert chunks
    assert "DeepSeek" in "".join(chunks)


async def test_deepseek_v4_flash_responses_returns_structured_semantic_eot() -> None:
    client = OpenAiCompatibleLlmClient(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        disable_thinking=True,
        api_style="responses",
        response_schema=EOT_RESPONSE_SCHEMA,
        response_schema_name="semantic_eot",
        timeout_s=30.0,
    )

    result = await LlmEotClassifier(client).classify(
        text="我想订一张从北京到",
        generation=1,
    )

    assert result.decision is EotDecision.INCOMPLETE
    assert result.confidence is not None
    assert result.source == "llm"


async def test_deepseek_v4_flash_returns_structured_semantic_interruption() -> None:
    client = OpenAiCompatibleLlmClient(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        disable_thinking=True,
        timeout_s=5.0,
    )

    result = await LlmSemanticInterruptionClassifier(client).classify(
        assistant_text="明天北京天气晴朗，最高温度二十八度。",
        transcript="不是北京，是上海，请按上海继续",
        boundary=InterruptionBoundary.SENTENCE_END,
        generation=1,
    )

    assert result.label in {
        InterruptionLabel.CORRECTION,
        InterruptionLabel.INTERRUPT,
    }
    assert 0 <= result.confidence <= 1
