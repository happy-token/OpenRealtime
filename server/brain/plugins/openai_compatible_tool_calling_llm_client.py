"""Real, network-calling `ToolCallingLlmClient` conformer.

See server/brain/llm_clients.py for the `ToolCallingLlmClient` Protocol and
`EchoToolCallingLlmClient`, the deterministic no-network default this real
conformer stands in for. Mirrors openai_compatible_llm_client.py's env-var,
urllib-in-a-thread, and always-stream conventions, but fully accumulates the
SSE stream before returning: deciding between a tool call and final text
requires the whole response message, not a token stream, so nothing is
exposed to the caller until the stream ends.

Statefulness note: follow-up calls carry only the newest tool result, while an
OpenAI-compatible request must resend the full assistant/tool message history.
The client therefore keeps one bounded turn's pending call and accumulated
messages in task-local state. A cancelled ``asyncio.to_thread`` request may
finish after its coroutine has exited, so instance-level state would let that
old provider thread corrupt the next Generation on the same connection.

Always requests `stream: true`, matching openai_compatible_llm_client.py's
convention, even though this client is non-streaming from its caller's
point of view (ADR-0033). The Bella gateway rejects any /chat/completions
request that omits it ("Stream must be set to true") — a plain
request/response call here would 400 against the one real backend this
client ships against. Deciding tool-call-vs-final-text still needs the
*whole* message, so the SSE deltas are fully accumulated before
`complete()` returns; nothing is streamed onward to the caller.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from contextvars import ContextVar
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import TYPE_CHECKING, Any

from server.brain.llm_clients import FinalText, LlmTurnResult, ToolCallRequest
from server.tools.canonical import CanonicalTool

if TYPE_CHECKING:
    from server.observability.telemetry import SessionTelemetry

logger = logging.getLogger(__name__)

_FALLBACK_TOOL_CALL_ID_PREFIX = "call_voiceagent_"
_DSML_MARKER = "<｜｜DSML｜｜"
_DSML_TOOL_CALL_PATTERN = re.compile(
    r'^\s*<｜｜DSML｜｜tool_calls>\s*'
    r'<｜｜DSML｜｜invoke\s+name="(?P<name>[^"]+)">\s*'
    r'(?P<parameters>.*?)\s*'
    r'</｜｜DSML｜｜invoke>\s*'
    r'</｜｜DSML｜｜tool_calls>\s*$',
    re.DOTALL,
)
_DSML_PARAMETER_PATTERN = re.compile(
    r'<｜｜DSML｜｜parameter\s+name="(?P<name>[^"]+)"'
    r'(?:\s+string="true")?>(?P<value>.*?)</｜｜DSML｜｜parameter>',
    re.DOTALL,
)
_CHANGING_FACT_MARKERS = (
    "天气",
    "气温",
    "新闻",
    "股价",
    "汇率",
    "路况",
    "交通",
    "比赛结果",
    "营业时间",
    "weather",
    "latest news",
)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class _PendingToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class _ToolTurnState:
    """Mutable state for one logical tool turn, isolated by asyncio task."""

    pending_tool_call: _PendingToolCall | None = None
    messages: list[dict[str, Any]] | None = None
    tool_call_count: int = 0


class OpenAiCompatibleToolCallingLlmClient:
    """Minimal client for any OpenAI-compatible /chat/completions endpoint
    that supports function/tool calling.

    Reads credentials from environment variables (never hardcoded, per
    security rules): VOICEAGENT_LLM_API_KEY (required),
    VOICEAGENT_LLM_BASE_URL (default "https://api.openai.com/v1"),
    VOICEAGENT_LLM_MODEL (default "gpt-4o-mini"), and
    VOICEAGENT_LLM_DISABLE_THINKING (default unset) when `disable_thinking`
    isn't passed explicitly — the same variables OpenAiCompatibleLlmClient
    reads, since both talk to the same endpoint.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        disable_thinking: bool | None = None,
        timeout_s: float = 15.0,
        telemetry: SessionTelemetry | None = None,
        provider_name: str = "openai_compatible",
    ) -> None:
        self._api_key = api_key or os.environ["VOICEAGENT_LLM_API_KEY"]
        self._base_url = (
            base_url or os.environ.get("VOICEAGENT_LLM_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self._model = model or os.environ.get("VOICEAGENT_LLM_MODEL") or "gpt-4o-mini"
        self._disable_thinking = (
            disable_thinking
            if disable_thinking is not None
            else _env_flag("VOICEAGENT_LLM_DISABLE_THINKING")
        )
        self._timeout_s = timeout_s
        self._telemetry = telemetry
        self._provider_name = provider_name
        self._turn_state: ContextVar[_ToolTurnState | None] = ContextVar(
            f"tool_turn_state_{id(self)}",
            default=None,
        )

    async def complete(
        self,
        *,
        system_prompt: str,
        user_text: str,
        tools: list[CanonicalTool],
        tool_result: str | None = None,
    ) -> LlmTurnResult:
        turn_state = self._turn_state.get()
        if tool_result is None:
            turn_state = _ToolTurnState()
            self._turn_state.set(turn_state)
        elif turn_state is None:
            raise RuntimeError(
                "complete() called with tool_result but no pending tool turn exists"
            )
        if self._telemetry is None:
            return await asyncio.to_thread(
                self._complete_sync,
                system_prompt,
                user_text,
                tools,
                tool_result,
                turn_state,
            )
        async with self._telemetry.provider_call(
            provider=self._provider_name,
            operation="tool_chat.complete",
            model=self._model,
            timeout_ms=self._timeout_s * 1000,
            attributes={
                "phase": "follow_up" if tool_result is not None else "plan",
                "tool_count": len(tools),
            },
        ):
            return await asyncio.to_thread(
                self._complete_sync,
                system_prompt,
                user_text,
                tools,
                tool_result,
                turn_state,
            )

    def _complete_sync(
        self,
        system_prompt: str,
        user_text: str,
        tools: list[CanonicalTool],
        tool_result: str | None,
        turn_state: _ToolTurnState,
    ) -> LlmTurnResult:
        messages = self._build_messages(
            system_prompt,
            user_text,
            tool_result,
            turn_state=turn_state,
        )
        body: dict[str, Any] = {"model": self._model, "stream": True, "messages": messages}
        if self._disable_thinking:
            body["thinking"] = {"type": "disabled"}
        # ADR-0044 supersedes the original one-tool restriction: a bounded
        # Voice Runtime turn may make sequential tool calls. Keep schemas on
        # follow-ups so compatible providers return structured tool_calls
        # instead of serializing their private control protocol into content.
        if tools:
            body["tools"] = [_tool_to_function_schema(tool) for tool in tools]
            # Calls remain sequential so execution and cancellation stay
            # deterministic inside the realtime latency budget.
            body["parallel_tool_calls"] = False
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        started_at = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                content, tool_calls = self._read_sse_stream(response)
        except TimeoutError:
            logger.warning(
                "tool-calling LLM request to %s timed out after %.1fms (timeout_s=%s)",
                self._base_url,
                (time.monotonic() - started_at) * 1000,
                self._timeout_s,
            )
            raise
        except urllib.error.URLError:
            logger.exception(
                "tool-calling LLM request to %s failed after %.1fms",
                self._base_url,
                (time.monotonic() - started_at) * 1000,
            )
            raise
        duration_ms = (time.monotonic() - started_at) * 1000
        logger.info(
            "tool-calling LLM request to %s completed in %.1fms",
            self._base_url,
            duration_ms,
        )
        return self._parse_stream_result(
            content,
            tool_calls,
            user_text=user_text,
            allowed_tool_names={tool.name for tool in tools},
            turn_state=turn_state,
        )

    @staticmethod
    def _read_sse_stream(response: HTTPResponse) -> tuple[str, list[dict[str, Any]]]:
        """Accumulates `delta.content` and `delta.tool_calls` fragments from an
        OpenAI-style SSE stream into one final content string and one fully
        assembled tool-call list, keyed by the stream's `index` field since a
        tool call's name and arguments each arrive across multiple chunks."""
        content_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            delta = json.loads(payload)["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                content_chunks.append(content)
            for fragment in delta.get("tool_calls") or []:
                accumulated = tool_calls_by_index.setdefault(
                    fragment["index"], {"id": None, "name": None, "arguments": ""}
                )
                if fragment.get("id"):
                    accumulated["id"] = fragment["id"]
                function_fragment = fragment.get("function") or {}
                if function_fragment.get("name"):
                    accumulated["name"] = function_fragment["name"]
                if function_fragment.get("arguments"):
                    accumulated["arguments"] += function_fragment["arguments"]
        tool_calls = [tool_calls_by_index[index] for index in sorted(tool_calls_by_index)]
        return "".join(content_chunks), tool_calls

    def _build_messages(
        self,
        system_prompt: str,
        user_text: str,
        tool_result: str | None,
        *,
        turn_state: _ToolTurnState,
    ) -> list[dict[str, Any]]:
        if tool_result is None:
            turn_state.pending_tool_call = None
            turn_state.tool_call_count = 0
            turn_state.messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            return list(turn_state.messages)
        pending = turn_state.pending_tool_call
        if pending is None or turn_state.messages is None:
            raise RuntimeError(
                "complete() called with tool_result but no pending tool call was "
                "recorded — the first complete() call must return a tool call"
            )
        turn_state.messages.append(
            {"role": "tool", "tool_call_id": pending.id, "content": tool_result}
        )
        return list(turn_state.messages)

    def _parse_stream_result(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
        *,
        user_text: str,
        allowed_tool_names: set[str],
        turn_state: _ToolTurnState,
    ) -> LlmTurnResult:
        dsml_call = _parse_deepseek_dsml_tool_call(content)
        if dsml_call is not None:
            if tool_calls:
                raise RuntimeError("model returned both structured and DSML tool calls")
            tool_calls = [
                {
                    "id": None,
                    "name": dsml_call.name,
                    "arguments": json.dumps(dsml_call.arguments, ensure_ascii=False),
                }
            ]
            content = ""
        if tool_calls:
            if len(tool_calls) > 1:
                preferred = _preferred_serial_tool_call(tool_calls, user_text)
                if preferred is None:
                    logger.warning(
                        "model requested %d tool calls despite serial mode; "
                        "using the first sequentially",
                        len(tool_calls),
                    )
                else:
                    logger.warning(
                        "model requested %d tool calls despite serial mode; "
                        "prioritizing search_web for changing facts",
                        len(tool_calls),
                    )
                    tool_calls = [preferred]
            call = tool_calls[0]
            arguments = json.loads(call["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise RuntimeError("tool call arguments must be a JSON object")
            if call["name"] not in allowed_tool_names:
                raise RuntimeError(f"model requested unknown tool {call['name']!r}")
            turn_state.tool_call_count += 1
            turn_state.pending_tool_call = _PendingToolCall(
                id=call["id"]
                or f"{_FALLBACK_TOOL_CALL_ID_PREFIX}{turn_state.tool_call_count}",
                name=call["name"],
                arguments=arguments,
            )
            if turn_state.messages is None:
                raise RuntimeError("tool turn messages were not initialized")
            turn_state.messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": turn_state.pending_tool_call.id,
                            "type": "function",
                            "function": {
                                "name": turn_state.pending_tool_call.name,
                                "arguments": json.dumps(
                                    turn_state.pending_tool_call.arguments,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            )
            return ToolCallRequest(name=call["name"], arguments=arguments)
        if _DSML_MARKER in content:
            raise RuntimeError("malformed DeepSeek DSML tool protocol in model content")
        turn_state.pending_tool_call = None
        turn_state.messages = None
        return FinalText(content)


def _preferred_serial_tool_call(
    tool_calls: list[dict[str, Any]],
    user_text: str,
) -> dict[str, Any] | None:
    normalized = user_text.strip().lower()
    if not any(marker in normalized for marker in _CHANGING_FACT_MARKERS):
        return None
    if not any(call.get("name") == "get_current_datetime" for call in tool_calls):
        return None
    return next((call for call in tool_calls if call.get("name") == "search_web"), None)


def _parse_deepseek_dsml_tool_call(content: str) -> ToolCallRequest | None:
    if _DSML_MARKER not in content:
        return None
    match = _DSML_TOOL_CALL_PATTERN.fullmatch(content)
    if match is None:
        raise RuntimeError("malformed DeepSeek DSML tool protocol in model content")
    parameter_block = match.group("parameters")
    arguments: dict[str, Any] = {}
    consumed_to = 0
    for parameter in _DSML_PARAMETER_PATTERN.finditer(parameter_block):
        if parameter_block[consumed_to : parameter.start()].strip():
            raise RuntimeError("malformed DeepSeek DSML tool parameter")
        name = html.unescape(parameter.group("name"))
        if name in arguments:
            raise RuntimeError(f"duplicate DeepSeek DSML tool parameter {name!r}")
        arguments[name] = html.unescape(parameter.group("value").strip())
        consumed_to = parameter.end()
    if parameter_block[consumed_to:].strip():
        raise RuntimeError("malformed DeepSeek DSML tool parameter")
    return ToolCallRequest(
        name=html.unescape(match.group("name")),
        arguments=arguments,
    )


def _tool_to_function_schema(tool: CanonicalTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
