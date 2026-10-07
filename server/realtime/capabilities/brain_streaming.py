"""Realtime adapters from stable Brain interfaces to incremental production."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from server.brain.base import Brain
from server.brain.llm_clients import ToolCallRequest
from server.brain.tool_calling_brain import ToolCallingBrain
from server.core.async_stream import OwnedStreamCleanupError, owned_async_iterator
from server.core.turn_content import TurnContent
from server.realtime.capabilities.tool_results import ToolResultChannel
from server.tools.canonical import LatencyClass

logger = logging.getLogger(__name__)


class StreamingTextBrain(Protocol):
    def stream(self, content: TurnContent) -> AsyncIterator[str]: ...


class BrainStreamingAdapter:
    """Prefer a Brain's native stream while preserving complete-only plugins."""

    def __init__(self, brain: Brain) -> None:
        self._brain = brain

    async def stream(self, content: TurnContent) -> AsyncIterator[str]:
        stream = getattr(self._brain, "stream", None)
        if stream is not None:
            async with owned_async_iterator(stream(content)) as iterator:
                async for delta in iterator:
                    if delta:
                        yield delta
            return
        response = await self._brain.respond(content)
        if response.text:
            yield response.text


@dataclass(frozen=True, slots=True)
class BrainToolCall:
    call_id: str
    tool_name: str
    tool_version: str
    arguments: dict[str, Any]
    latency: LatencyClass

    def __post_init__(self) -> None:
        if not self.call_id or not self.tool_name or not self.tool_version:
            raise ValueError("Brain tool call identity must be non-empty")


@dataclass(frozen=True, slots=True)
class BrainDelegationCall:
    """Provider-neutral request for durable application work."""

    delegation_request_id: str
    instruction: str
    agent_name: str | None = None

    def __post_init__(self) -> None:
        if not self.delegation_request_id or not self.instruction:
            raise ValueError("Brain delegation identity and instruction must be non-empty")


@dataclass(frozen=True, slots=True)
class _RelayedStreamFailure:
    error: Exception


_RELAYED_STREAM_COMPLETED = object()


class ToolCallingBrainStreamingAdapter:
    """Turns a tool-planning Brain into a pause/resume Engine input stream."""

    def __init__(self, brain: ToolCallingBrain) -> None:
        self._brain = brain

    async def stream_with_tools(
        self,
        content: TurnContent,
        *,
        tool_results: ToolResultChannel,
    ) -> AsyncIterator[str | BrainToolCall]:
        result = await self._brain.begin_turn(content)
        tool_calls = 0
        max_tool_calls = getattr(self._brain, "max_tool_calls", 3)
        while isinstance(result, ToolCallRequest):
            tool_calls += 1
            if tool_calls > max_tool_calls:
                raise RuntimeError("bounded Fast Tool Loop exhausted its tool-call budget")
            tool = self._brain.resolve_tool(result.name)
            if tool is None:
                raise ValueError(f"model requested unknown tool {result.name!r}")
            call_id = _stable_call_id(content, result)
            yield BrainToolCall(
                call_id=call_id,
                tool_name=tool.name,
                tool_version=tool.version,
                arguments=result.arguments,
                latency=tool.latency,
            )
            if tool.latency is LatencyClass.VARIABLE:
                yield "我查一下，马上告诉你。"
            feedback = await tool_results.wait(call_id)
            result = await self._brain.continue_turn(
                content,
                tool_result=feedback.model_output,
            )
        if result.text:
            yield result.text


class VoiceRuntimeBrainStreamingAdapter:
    """Route bounded daily realtime intents to tools and stream chat directly.

    The interface stays identical to the tool-capable Engine input stream. The
    routing implementation is deliberately local and side-effect free so an
    ordinary chat turn does not pay for a separate LLM planning round-trip.
    """

    _TOOL_INTENT_MARKERS = (
        "get_current_datetime",
        "search_web",
        "几点",
        "什么时间",
        "当前时间",
        "现在时间",
        "今天几号",
        "星期几",
        "日期",
        "天气",
        "气温",
        "新闻",
        "股价",
        "汇率",
        "路况",
        "实时交通",
        "比赛结果",
        "营业时间",
        "搜索",
        "搜一下",
        "查一下",
        "查询一下",
        "what time",
        "current time",
        "weather",
        "latest news",
        "search for",
    )
    _SLOW_TOOL_INTENT_MARKERS = (
        "search_web",
        "天气",
        "气温",
        "新闻",
        "股价",
        "汇率",
        "路况",
        "实时交通",
        "比赛结果",
        "营业时间",
        "搜索",
        "搜一下",
        "查一下",
        "查询一下",
        "weather",
        "latest news",
        "search for",
    )
    _SLOW_TOOL_ACK = "我查一下，马上告诉你。"
    _SLOW_TOOL_ACK_POOLS: ClassVar[dict[str, tuple[str, ...]]] = {
        "weather": (
            "我帮你看看天气。",
            "好的，我查一下天气情况。",
            "稍等，我看看最新天气。",
        ),
        "news": (
            "我看看最新消息。",
            "好的，我帮你查一下最新消息。",
            "稍等，我确认一下最新信息。",
        ),
        "finance": (
            "我帮你看看最新行情。",
            "好的，我确认一下当前数据。",
            "稍等，我查一下最新报价。",
        ),
        "traffic": (
            "我帮你看看实时路况。",
            "好的，我确认一下当前交通情况。",
            "稍等，我查一下最新路况。",
        ),
        "sports": (
            "我帮你看看最新赛果。",
            "好的，我确认一下比赛结果。",
            "稍等，我查一下最新赛况。",
        ),
        "business_hours": (
            "我帮你确认一下营业时间。",
            "好的，我看看今天几点营业。",
            "稍等，我查一下营业安排。",
        ),
        "search": (
            "我查一下相关信息。",
            "好的，我帮你找找。",
            "稍等，我确认一下。",
        ),
    }
    _SLOW_TOOL_REVISION_ACK = "好的，我按完整问题查一下。"
    _SLOW_TOOL_FAILURE = "查询服务暂时出了点问题，请稍后再试。"
    _SLOW_TOOL_ACK_REVISION_WINDOW_S = 3.0
    _ELLIPTICAL_TOOL_FOLLOW_UP_MARKERS = (
        "我在",
        "在这",
        "今天",
        "明天",
        "后天",
        "昨晚",
        "今晚",
        "上午",
        "下午",
        "晚上",
    )

    def __init__(
        self,
        *,
        chat: StreamingTextBrain,
        tools: ToolCallingBrainStreamingAdapter,
        clock: Callable[[], float] = time.monotonic,
        slow_tool_ack_delay_s: float = 0.5,
    ) -> None:
        if slow_tool_ack_delay_s < 0:
            raise ValueError("slow_tool_ack_delay_s must be non-negative")
        self._chat = chat
        self._tools = tools
        self._clock = clock
        self._slow_tool_ack_delay_s = slow_tool_ack_delay_s
        self._last_slow_ack: tuple[int, str, float] | None = None
        self._slow_tool_ack_cursors: dict[str, int] = {}

    async def close(self) -> None:
        close = getattr(self._chat, "close", None)
        if close is not None:
            await close()

    async def prepare(self, turn: TurnContent) -> bool:
        """Speculate only on the side-effect-free ordinary-chat branch."""

        if self.should_use_tools_for_turn(turn):
            invalidate = getattr(self._chat, "invalidate", None)
            if invalidate is not None:
                await invalidate(turn.generation, reason="tool_intent")
            return False
        prepare = getattr(self._chat, "prepare", None)
        if prepare is None:
            return False
        return await prepare(turn)

    async def invalidate(self, generation: int, *, reason: str) -> bool:
        invalidate = getattr(self._chat, "invalidate", None)
        if invalidate is None:
            return False
        return await invalidate(generation, reason=reason)

    @classmethod
    def should_use_tools(cls, transcript: str) -> bool:
        normalized = transcript.strip().lower()
        return any(marker in normalized for marker in cls._TOOL_INTENT_MARKERS)

    @classmethod
    def should_acknowledge_slow_tool(cls, transcript: str) -> bool:
        normalized = transcript.strip().lower()
        return any(marker in normalized for marker in cls._SLOW_TOOL_INTENT_MARKERS)

    @classmethod
    def should_use_tools_for_turn(cls, turn: TurnContent) -> bool:
        if cls.should_use_tools(turn.text):
            return True
        if not turn.conversation_context or not cls.should_use_tools(
            turn.conversation_context
        ):
            return False
        normalized = turn.text.strip().lower()
        if not normalized or len(normalized) > 24:
            return False
        return normalized.endswith(("的", "呢")) or any(
            marker in normalized
            for marker in cls._ELLIPTICAL_TOOL_FOLLOW_UP_MARKERS
        )

    async def stream_with_tools(
        self,
        content: TurnContent,
        *,
        tool_results: ToolResultChannel,
    ) -> AsyncIterator[str | BrainToolCall]:
        if self.should_use_tools_for_turn(content):
            invalidate = getattr(self._chat, "invalidate", None)
            if invalidate is not None:
                await invalidate(content.generation, reason="tool_intent")
            acknowledgement_source = (
                content.text
                if self.should_use_tools(content.text)
                else content.model_text
            )
            acknowledged = self.should_acknowledge_slow_tool(acknowledgement_source)
            if acknowledged:
                acknowledgement_text = (
                    self._SLOW_TOOL_REVISION_ACK
                    if self._is_immediate_transcript_extension(content)
                    else self._next_slow_tool_ack(acknowledgement_source)
                )
            try:
                tool_stream = self._tools.stream_with_tools(
                    content,
                    tool_results=tool_results,
                )
                events = (
                    self._stream_with_delayed_acknowledgement(
                        tool_stream,
                        acknowledgement_text=acknowledgement_text,
                        content=content,
                    )
                    if acknowledged else tool_stream
                )
                async with owned_async_iterator(events) as iterator:
                    async for event in iterator:
                        yield event
            except Exception as error:
                if not acknowledged or isinstance(error, OwnedStreamCleanupError):
                    raise
                logger.exception(
                    "slow realtime tool turn failed: generation=%s error_type=%s",
                    content.generation,
                    type(error).__name__,
                )
                yield self._SLOW_TOOL_FAILURE
            return
        async with owned_async_iterator(self._chat.stream(content)) as iterator:
            async for delta in iterator:
                yield delta

    async def _stream_with_delayed_acknowledgement(
        self,
        stream: AsyncIterator[str | BrainToolCall],
        *,
        acknowledgement_text: str,
        content: TurnContent,
    ) -> AsyncIterator[str | BrainToolCall]:
        deadline = self._clock() + self._slow_tool_ack_delay_s
        acknowledgement_emitted = False
        iterator = stream.__aiter__()
        relayed: asyncio.Queue[object] = asyncio.Queue(maxsize=1)

        relay_cleanup_error: Exception | None = None

        async def relay_stream() -> None:
            nonlocal relay_cleanup_error
            try:
                async for event in iterator:
                    await relayed.put(event)
            except Exception as error:  # noqa: BLE001 - async stream relay boundary
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    relay_cleanup_error = error
                await relayed.put(_RelayedStreamFailure(error))
            else:
                await relayed.put(_RELAYED_STREAM_COMPLETED)

        producer = asyncio.create_task(relay_stream())
        pending: asyncio.Task[object] | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(relayed.get())
                if not acknowledgement_emitted:
                    remaining = max(0.0, deadline - self._clock())
                    done, _ = await asyncio.wait((pending,), timeout=remaining)
                    if not done:
                        acknowledgement_emitted = True
                        self._last_slow_ack = (
                            content.generation,
                            _normalized_utterance(content.text),
                            self._clock(),
                        )
                        yield acknowledgement_text
                        continue
                event = await pending
                pending = None
                if event is _RELAYED_STREAM_COMPLETED:
                    return
                if isinstance(event, _RelayedStreamFailure):
                    raise event.error
                assert isinstance(event, (str, BrainToolCall))
                if event == self._SLOW_TOOL_ACK:
                    continue
                yield event
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            if not producer.done() and not producer.cancelling():
                producer.cancel()
            results = await asyncio.gather(producer, return_exceptions=True)
            async with owned_async_iterator(iterator):
                pass
            if relay_cleanup_error is not None:
                raise OwnedStreamCleanupError(f"tool stream cleanup failed: {relay_cleanup_error}") from relay_cleanup_error
            for result in results:
                if isinstance(result, Exception):
                    raise OwnedStreamCleanupError(f"tool relay cleanup failed: {result}") from result

    def _next_slow_tool_ack(self, transcript: str) -> str:
        normalized = transcript.strip().lower()
        if any(marker in normalized for marker in ("天气", "气温", "weather")):
            intent = "weather"
        elif any(marker in normalized for marker in ("新闻", "latest news")):
            intent = "news"
        elif any(marker in normalized for marker in ("股价", "汇率")):
            intent = "finance"
        elif any(marker in normalized for marker in ("路况", "实时交通")):
            intent = "traffic"
        elif "比赛结果" in normalized:
            intent = "sports"
        elif "营业时间" in normalized:
            intent = "business_hours"
        else:
            intent = "search"
        pool = self._SLOW_TOOL_ACK_POOLS[intent]
        cursor = self._slow_tool_ack_cursors.get(intent, 0)
        self._slow_tool_ack_cursors[intent] = cursor + 1
        return pool[cursor % len(pool)]

    def _is_immediate_transcript_extension(self, content: TurnContent) -> bool:
        previous = self._last_slow_ack
        if previous is None:
            return False
        previous_generation, previous_text, acknowledged_at = previous
        current_text = _normalized_utterance(content.text)
        return (
            content.generation == previous_generation + 1
            and self._clock() - acknowledged_at
            <= self._SLOW_TOOL_ACK_REVISION_WINDOW_S
            and bool(previous_text)
            and bool(current_text)
            and (
                current_text.startswith(previous_text)
                or previous_text.startswith(current_text)
            )
        )


def _stable_call_id(content: TurnContent, request: ToolCallRequest) -> str:
    arguments = json.dumps(
        request.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"urn:voiceagent:tool:{content.generation}:{request.name}:{arguments}",
        )
    )


def _normalized_utterance(text: str) -> str:
    return "".join(
        character.lower()
        for character in text.strip()
        if character not in "，。！？,.!?；;：:、 \t\r\n"
    )
