"""ChatBrain: the framework's built-in default Brain.

Simple, local, handles natural conversation. Complex/delegated tasks are the
Router's job to send elsewhere (ADR-0001) — ChatBrain only ever answers
directly. See CONTEXT.md — Brain.

Grounds every turn's system prompt with the real current date/time (see
ADR-0030). This matters because ChatBrain is the live demo's default Brain
whenever tool-calling isn't opted into (VOICEAGENT_DEMO_TOOLS unset) — with
no tools reachable, without this grounding the model would have to guess
"today" from stale training data. A real tool-calling conformer,
OpenAiCompatibleToolCallingLlmClient (ADR-0029), does now exist for
ToolCallingBrain's opt-in path (ADR-0032), where `ClockToolSource`'s
`get_current_datetime` tool grounds datetime instead — this file's own
grounding still covers the default, tools-off path.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from server.brain.base import BrainResponse
from server.brain.llm_clients import LlmClient
from server.brain.realtime_grounding import TurnGrounder
from server.core.turn_content import TurnContent
from server.tools.clock_source import localize

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant. "
    "Respond in one or two short spoken sentences. "
    "Answer in the same language as the user's latest request. When the user "
    "speaks Chinese, answer only in natural Chinese except for unavoidable "
    "proper nouns. Never expose chain-of-thought, internal reasoning, hidden "
    "analysis, or meta-commentary about interpreting the user's request. "
    "Return only the answer intended for the user."
)

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_META_REASONING_PATTERN = re.compile(
    r"\b(?:let me|the user|user is|message seems|unclear|garbled|"
    r"i need|i should|we need|reconsider|analy[sz](?:e|ing))\b",
    re.IGNORECASE,
)
_CHINESE_RETRY_MESSAGE = "抱歉，我刚才没有正确生成中文回复，请再说一遍。"


class ChatBrain:
    def __init__(
        self,
        llm_client: LlmClient,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        system_prompt_transform: Callable[[str], str] | None = None,
        tz_name: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        grounder: TurnGrounder | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._system_prompt_transform = system_prompt_transform
        self._tz_name = tz_name
        self._now = now
        self._grounder = grounder

    async def respond(self, content: TurnContent) -> BrainResponse:
        grounded_prompt, user_text = await self._prepare_prompts(content)
        text = await self._llm_client.complete(
            system_prompt=grounded_prompt, user_text=user_text
        )
        text = _sanitize_response_language(text, input_text=content.model_text)
        return BrainResponse(text=text, generation=content.generation)

    async def stream(self, content: TurnContent) -> AsyncIterator[str]:
        """Yield provider deltas, falling back to one complete response chunk."""

        grounded_prompt, user_text = await self._prepare_prompts(content)
        stream = getattr(self._llm_client, "stream", None)
        if stream is None:
            text = await self._llm_client.complete(
                system_prompt=grounded_prompt,
                user_text=user_text,
            )
            yield _sanitize_response_language(text, input_text=content.model_text)
            return
        language_guard = _LeadingForeignPreambleGuard(input_text=content.model_text)
        async for delta in stream(
            system_prompt=grounded_prompt,
            user_text=user_text,
        ):
            if delta:
                filtered = language_guard.feed(delta)
                if filtered:
                    yield filtered
        final = language_guard.finish()
        if final:
            yield final

    def _grounded_prompt(self) -> str:
        return f"{self._current_system_prompt()}\n\n{self._datetime_grounding()}"

    def _current_system_prompt(self) -> str:
        if self._system_prompt_transform is None:
            return self._system_prompt
        return self._system_prompt_transform(self._system_prompt)

    async def _prepare_prompts(self, content: TurnContent) -> tuple[str, str]:
        transcript = content.text
        model_text = content.model_text
        if self._grounder is None:
            return self._grounded_prompt(), model_text
        grounding = await self._grounder.resolve(transcript)
        system_prompt = f"{self._current_system_prompt()}\n\n{grounding.system_context()}"
        user_context = grounding.user_context()
        user_text = model_text if not user_context else f"{model_text}\n\n{user_context}"
        return system_prompt, user_text

    def _datetime_grounding(self) -> str:
        localized, tz_name = localize(self._now(), self._tz_name)
        weekday = localized.strftime("%A")
        return (
            f"当前时间：{localized.isoformat()}（{tz_name}，{weekday}）。"
            "回答日期/时间相关问题以此为准，不要凭训练数据猜测当前日期或年份。"
        )


class _LeadingForeignPreambleGuard:
    """Hold a non-Chinese prefix until it is safe to expose to UI/TTS."""

    def __init__(self, *, input_text: str) -> None:
        self._enabled = bool(_CJK_PATTERN.search(input_text))
        self._decided = not self._enabled
        self._buffer = ""

    def feed(self, delta: str) -> str:
        if self._decided:
            return delta
        self._buffer += delta
        match = _CJK_PATTERN.search(self._buffer)
        if match is None:
            return ""
        prefix = self._buffer[: match.start()]
        buffered = self._buffer
        self._buffer = ""
        self._decided = True
        if _looks_like_meta_reasoning(prefix):
            return buffered[match.start() :].lstrip()
        return buffered

    def finish(self) -> str:
        if not self._buffer:
            return ""
        buffered = self._buffer
        self._buffer = ""
        self._decided = True
        if _looks_like_meta_reasoning(buffered):
            return _CHINESE_RETRY_MESSAGE
        return buffered


def _looks_like_meta_reasoning(text: str) -> bool:
    return not _CJK_PATTERN.search(text) and bool(_META_REASONING_PATTERN.search(text))


def _sanitize_response_language(text: str, *, input_text: str) -> str:
    guard = _LeadingForeignPreambleGuard(input_text=input_text)
    return f"{guard.feed(text)}{guard.finish()}"
