"""Jev Choice adapters; turn ownership, deadlines and cancellation stay in the runtime."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Protocol

from server.turn_policy.classifier_execution import (
    CLASSIFIER_STAGE_OBSERVER,
    classification_stage,
)
from server.turn_policy.eot_classifier import EotClassification, EotDecision, EotRequest
from server.turn_policy.semantic_input import SemanticInputState
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
)

# Compatibility aliases for existing diagnostics callers; ownership is generic.
JEV_TIMING_OBSERVER = CLASSIFIER_STAGE_OBSERVER


def _timed_stage(stage: str):
    return classification_stage("jev", stage)


EOT_CRITERIA = {
    "complete": "当前表达已经形成可回应的完整意图，缺少可追问的执行参数不等于未说完",
    "incomplete": "句尾语法或意思悬空，仍依赖即将补充的必需宾语、谓语或后续表达",
    "uncertain": "转写证据不足或相互矛盾，不能可靠判断是否说完",
}
INTERRUPTION_CRITERIA = {
    "backchannel": "当前用户附和，鼓励助手继续，不要求停播",
    "stop": "当前用户只要求停止，没有新任务",
    "correction": "当前用户纠正正在回答依赖的信息，需要停播",
    "interrupt": "当前用户提出新任务、补充要求或切换话题，需要接管话轮",
    "ignore": "旁人讲话、背景音或与助手无关的声音，不应停播",
    "uncertain": "证据不足以可靠判断是否应该停播",
}
EOT_INSTRUCTIONS = (
    "判断 transcript 当前表达是否语义完整，结合 history 理解省略和指代。"
    "transcript 是截至该候选边界的累计文本，即使 input_state 包含 chunk_id 也不是独立新块；"
    "previous_chunks 只是辅助上下文，不要重复拼接。必须判断整段累计意图，不能只判断末块。"
    "句尾的介词、连词、动作或修饰语仍等待必需对象或后续谓语时选 incomplete；"
    "不要替用户补完。意图清楚但缺少可追问的执行参数时选 complete。"
    "不以标点、停顿、speech_active 或 ASR boundary 代替语义完整性。"
)
INTERRUPTION_INSTRUCTIONS = (
    "助手正在播报。有 cumulative_transcript 时，它是截至该候选边界的累计文本，"
    "必须判断整段累计意图；transcript 仍是此次封口的独立新块，previous_chunks 只是辅助上下文。"
    "尾部附和不能覆盖前面仍有效的停止、纠正或新任务；只有明确撤回或纠正此前要求时才改变整段意图。"
    "没有 cumulative_transcript 时，按 transcript 与 previous_chunks 判断，特别注意跨块否定和纠正。"
    "先根据 observation 判断待分类文本是否来自当前用户并指向助手，"
    "再结合 assistant_playback 和 history 判断动作。明确观察到电视、旁人对其他设备说话、"
    "回声或非语音噪声时选 ignore，即使词面是停播或新任务。没有排除证据时按用户意图判断。"
    "缺少声源观察不证明是背景音；不能推断说话者身份。不要判断用户是否说完，"
    "boundary 只表示转写边界；证据冲突、识别乱码或意图不清时选 uncertain，不代表接管话轮。"
    "嗯、嗯嗯、哼哼、好、可以等短附和在没有新要求或纠正时选 backchannel，不能因出现用户声音就选 interrupt。"
    "即使助手尚未开始播放，也需要明确停止、纠正或新任务的语义证据才能选 stop、correction 或 interrupt。"
)


@dataclass(frozen=True, slots=True)
class JevChoice:
    label: str
    confidence: float
    model: str
    probabilities: tuple[tuple[str, float], ...]


class JevChoiceClient(Protocol):
    async def choose(
        self, *, state: dict[str, Any], instructions: str, criteria: dict[str, str]
    ) -> JevChoice: ...


class JevClient:
    """Cancellation-friendly async SDK transport with no retries on the realtime path."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "jev-1.13.0",
        timeout_s: float = 2.0,
        max_concurrency: int = 2,
        observer: Callable[[JevChoice], None] | None = None,
        reuse_connections: bool = False,
    ) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError("Jev requires a server-side API key and model")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("Jev timeout must be finite and positive")
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError("Jev concurrency must be a positive integer")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._slots = asyncio.Semaphore(max_concurrency)
        self._observer = observer
        self._reuse_connections = reuse_connections
        self._client: Any = None
        self._client_stack = AsyncExitStack()
        self._client_lock = asyncio.Lock()
        self._closed = False

    async def close(self) -> None:
        # Revoke admission before waiting for any in-flight connection setup.
        self._closed = True
        async with self._client_lock:
            await self._client_stack.aclose()
            self._client = None

    async def _shared_client(self, factory: Callable[[], Any]) -> Any:
        async with self._client_lock:
            if self._closed:
                raise RuntimeError("Jev client is closed")
            if self._client is None:
                self._client = await self._client_stack.enter_async_context(factory())
            return self._client

    async def choose(
        self, *, state: dict[str, Any], instructions: str, criteria: dict[str, str]
    ) -> JevChoice:
        try:
            from typesafe_sdk import AsyncTypeSafeClient, Choice, RetryPolicy
        except ImportError as exc:
            raise RuntimeError("Jev requires uv sync --extra jev") from exc
        if self._closed:
            raise RuntimeError("Jev client is closed")

        def create_client():
            return AsyncTypeSafeClient(
                api_key=self._api_key,
                model=self._model,
                timeout=self._timeout_s,
                retry=RetryPolicy(max_retries=0),
            )

        # The deadline includes semaphore waiting; shared transport survives request cancellation.
        async with asyncio.timeout(self._timeout_s):
            with _timed_stage("slot_wait"):
                await self._slots.acquire()
            try:
                # The owner can close while this call waits behind another session.
                if self._closed:
                    raise RuntimeError("Jev client is closed")
                async with AsyncExitStack() as stack:
                    with _timed_stage("client_ready"):
                        client = (
                            await self._shared_client(create_client)
                            if self._reuse_connections
                            else await stack.enter_async_context(create_client())
                        )
                    # Fresh-client setup can also suspend across owner shutdown.
                    if self._closed:
                        raise RuntimeError("Jev client is closed")
                    with _timed_stage("request"):
                        response = await client.system_one(
                            state=state,
                            questions={"decision": Choice(instructions=instructions, criteria=criteria)},
                        )
                    with _timed_stage("decode"):
                        answer = response.choices["decision"]
                        result = JevChoice(
                            answer.choice, answer.confidence, response.model,
                            tuple(answer.probabilities.items()),
                        )
            finally:
                self._slots.release()
        _validate_choice(result, criteria)
        if self._observer is not None:
            self._observer(result)
        return result


def _validate_choice(result: JevChoice, criteria: dict[str, str]) -> None:
    if result.label not in criteria or not result.model:
        raise ValueError("invalid Jev choice/model")
    if (
        isinstance(result.confidence, bool)
        or not math.isfinite(result.confidence)
        or not 0 <= result.confidence <= 1
    ):
        raise ValueError("invalid Jev confidence")
    probabilities = dict(result.probabilities)
    if len(probabilities) != len(result.probabilities) or set(probabilities) != set(criteria):
        raise ValueError("Jev probabilities must cover exactly the requested choices")
    if any(
        isinstance(p, bool) or not math.isfinite(p) or not 0 <= p <= 1
        for p in probabilities.values()
    ):
        raise ValueError("invalid Jev probability")
    if not math.isclose(sum(probabilities.values()), 1, abs_tol=0.02):
        raise ValueError("Jev probabilities must sum to one")


def _input_state(state: SemanticInputState) -> dict[str, Any]:
    return {
        key: value.value if isinstance(value, Enum) else value
        for key, value in asdict(state).items()
    }


class JevEotClassifier:
    def __init__(self, client: JevChoiceClient, *, min_confidence: float = 0.8) -> None:
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("Jev EOT confidence threshold must be between zero and one")
        self._client = client
        self._min_confidence = min_confidence

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        return await self.classify_request(EotRequest(text=text, generation=generation))

    async def classify_request(self, request: EotRequest) -> EotClassification:
        result = await self._client.choose(
            state={
                "transcript": request.text,
                "history": [asdict(message) for message in request.context.history],
                "input_state": _input_state(request.input_state),
            },
            instructions=EOT_INSTRUCTIONS,
            criteria=EOT_CRITERIA,
        )
        _validate_choice(result, EOT_CRITERIA)
        decision = EotDecision(result.label)
        if result.confidence < self._min_confidence:
            decision = EotDecision.UNCERTAIN
        return EotClassification(
            decision, confidence=result.confidence, source=f"jev:{result.model}"
        )


class JevSemanticInterruptionClassifier:
    def __init__(self, client: JevChoiceClient) -> None:
        self._client = client

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        return await self.classify_request(
            InterruptionRequest(
                transcript=transcript,
                assistant_text=assistant_text,
                boundary=boundary,
                generation=generation,
            )
        )

    async def classify_request(self, request: InterruptionRequest) -> InterruptionClassification:
        result = await self._client.choose(
            state={
                "transcript": request.transcript,
                **(
                    {"cumulative_transcript": request.cumulative_transcript}
                    if request.cumulative_transcript is not None
                    else {}
                ),
                "assistant_playback": request.assistant_text,
                "history": [asdict(message) for message in request.history],
                "boundary": request.boundary.value,
                "input_state": _input_state(request.input_state),
                "observation": "unknown: no acoustic source identity supplied",
            },
            instructions=INTERRUPTION_INSTRUCTIONS,
            criteria=INTERRUPTION_CRITERIA,
        )
        _validate_choice(result, INTERRUPTION_CRITERIA)
        return InterruptionClassification(InterruptionLabel(result.label), result.confidence)
