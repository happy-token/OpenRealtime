"""LLM conformer for the provider-neutral semantic interruption seam."""

from __future__ import annotations

import json
from dataclasses import asdict

from server.brain.llm_clients import LlmClient
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionRequest,
    parse_interruption_classification,
)

DEFAULT_SYSTEM_PROMPT = (
    "你是实时语音助手的语义打断分类器。只判断助手正在播报时，当前用户累计文本"
    "是否要求立即停播；不要判断用户是否已经说完。"
    "stop 表示只要求停止、没有新任务；correction 表示纠正当前回答依赖的信息；"
    "interrupt 表示以新任务、补充信息或新话题取得话轮；backchannel 表示附和并让"
    "助手继续；ignore 表示不应采取动作；证据不足用 uncertain。"
    "只输出 JSON，且只能有两个字段："
    '{"label":"stop|correction|interrupt|backchannel|ignore|uncertain",'
    '"confidence":0.0}。'
)


class LlmSemanticInterruptionClassifier:
    """Classify one frozen ASR revision through the existing ``LlmClient``.

    Timeout, revision cancellation, thresholding, and fail-open behavior live
    in ``SemanticInterruptionGate`` so every model conformer shares the same
    concurrency semantics.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt

    async def classify_request(self, request: InterruptionRequest) -> InterruptionClassification:
        payload = {
            "assistant_playback": request.assistant_text,
            "transcript": request.transcript,
            "boundary": request.boundary.value,
            "history": [
                {"role": message.role, "content": message.content} for message in request.history
            ],
            "input_state": asdict(request.input_state),
        }
        return await self._classify_payload(payload)

    async def _classify_payload(self, payload: dict) -> InterruptionClassification:
        content = await self._llm_client.complete(
            system_prompt=self._system_prompt,
            user_text=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=lambda value: value.value,
            ),
        )
        return parse_interruption_classification(content)

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del generation  # revision/generation validity is owned by the Gate
        return await self._classify_payload(
            {
                "assistant_playback": assistant_text,
                "transcript": transcript,
                "boundary": boundary.value,
            }
        )
