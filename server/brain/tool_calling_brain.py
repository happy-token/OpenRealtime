"""ToolCallingBrain: a Brain with a bounded sequential Fast Tool Loop.

Small dependent tool chains are allowed by ADR-0044. The configured call cap
keeps realtime work bounded; genuinely open-ended work belongs in Agent Runtime.
"""

from __future__ import annotations

from collections.abc import Callable

from server.brain.base import BrainResponse
from server.brain.llm_clients import LlmTurnResult, ToolCallingLlmClient, ToolCallRequest
from server.core.turn_content import TurnContent
from server.tools.registry import ToolRegistry

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant. "
    "Respond in one or two short spoken sentences. "
    "Answer in the same language as the user's latest request. When the user "
    "speaks Chinese, answer only in natural Chinese except for unavoidable "
    "proper nouns. Never expose chain-of-thought, internal reasoning, hidden "
    "analysis, or meta-commentary. "
    "Use a tool when it would help answer the user's request. "
    "Use the fewest tool calls needed and never repeat a tool unnecessarily. "
    "For a request only about the current date or time, call get_current_datetime. "
    "For current weather, news, traffic, markets, sports, or other changing facts, "
    "call search_web directly and do not call get_current_datetime first; preserve "
    "words such as today or tomorrow in the search query."
)


class ToolCallingBrain:
    def __init__(
        self,
        llm_client: ToolCallingLlmClient,
        tool_registry: ToolRegistry,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        system_prompt_transform: Callable[[str], str] | None = None,
        max_tool_calls: int = 3,
    ) -> None:
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._system_prompt = system_prompt
        self._system_prompt_transform = system_prompt_transform
        self._max_tool_calls = max_tool_calls

    async def respond(self, content: TurnContent) -> BrainResponse:
        result = await self.begin_turn(content)
        tool_calls = 0
        while isinstance(result, ToolCallRequest):
            tool_calls += 1
            if tool_calls > self._max_tool_calls:
                raise RuntimeError("bounded Fast Tool Loop exhausted its tool-call budget")
            tool = self._tool_registry.get(result.name)
            assert tool is not None, f"LLM requested unknown tool {result.name!r}"
            tool_result = await tool.handler(result.arguments)
            result = await self.continue_turn(content, tool_result=tool_result)
        return BrainResponse(text=result.text, generation=content.generation)

    async def begin_turn(self, content: TurnContent) -> LlmTurnResult:
        return await self._llm_client.complete(
            system_prompt=self._current_system_prompt(),
            user_text=content.model_text,
            tools=self._tool_registry.as_list(),
        )

    async def continue_turn(
        self,
        content: TurnContent,
        *,
        tool_result: str,
    ) -> LlmTurnResult:
        return await self._llm_client.complete(
            system_prompt=self._current_system_prompt(),
            user_text=content.model_text,
            tools=self._tool_registry.as_list(),
            tool_result=tool_result,
        )

    def _current_system_prompt(self) -> str:
        if self._system_prompt_transform is None:
            return self._system_prompt
        return self._system_prompt_transform(self._system_prompt)

    @property
    def max_tool_calls(self) -> int:
        return self._max_tool_calls

    def resolve_tool(self, name: str):
        return self._tool_registry.get(name)
