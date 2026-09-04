"""LLM client Protocols consumed by ChatBrain/ToolCallingBrain, plus the
framework's zero-config, deterministic defaults.

Model dependencies are pluggable — this module ships a deterministic
EchoLlmClient/EchoToolCallingLlmClient (for tests/demo, no network); the real,
network-calling conformers live in brain/plugins/ —
`OpenAiCompatibleLlmClient` (plain) and `OpenAiCompatibleToolCallingLlmClient`
(tool-calling, see ADR-0029). None of these are a Brain itself; see
brain/chat_brain.py and brain/tool_calling_brain.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from server.tools.canonical import CanonicalTool


class LlmClient(Protocol):
    async def complete(self, *, system_prompt: str, user_text: str) -> str: ...


class StreamingLlmClient(LlmClient, Protocol):
    def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
    ) -> AsyncIterator[str]: ...


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("chat message role is unsupported")
        if not self.content:
            raise ValueError("chat message content must be non-empty")


class MessageStreamingLlmClient(Protocol):
    """Optional structured-message seam used by prefix-cache-aware callers."""

    def stream_messages(
        self,
        *,
        messages: tuple[ChatMessage, ...],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class FinalText:
    text: str


@dataclass(frozen=True)
class ToolCallRequest:
    name: str
    arguments: dict


LlmTurnResult = FinalText | ToolCallRequest


class ToolCallingLlmClient(Protocol):
    async def complete(
        self,
        *,
        system_prompt: str,
        user_text: str,
        tools: list[CanonicalTool],
        tool_result: str | None = None,
    ) -> LlmTurnResult: ...


class EchoLlmClient:
    """Deterministic stand-in with no network dependency — for tests and demos."""

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        return f"You said: {user_text}"

    async def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
    ) -> AsyncIterator[str]:
        del system_prompt
        yield "You said: "
        yield user_text


class EchoToolCallingLlmClient:
    """Deterministic stand-in with no network dependency — for tests and demos.

    Generic over whatever tools are registered: requests the first tool
    whose name appears in the user's text, then finalizes from the tool
    result. No tool name is hardcoded.
    """

    async def complete(
        self,
        *,
        system_prompt: str,
        user_text: str,
        tools: list[CanonicalTool],
        tool_result: str | None = None,
    ) -> LlmTurnResult:
        if tool_result is not None:
            return FinalText(f"Tool said: {tool_result}")
        for tool in tools:
            if tool.name in user_text:
                return ToolCallRequest(name=tool.name, arguments={})
        return FinalText(f"You said: {user_text}")
