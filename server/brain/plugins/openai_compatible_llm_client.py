"""Real, network-calling `LlmClient` conformer.

See server/brain/llm_clients.py for the `LlmClient` Protocol and the
deterministic no-network defaults this real conformer stands in for.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import TYPE_CHECKING, Any, Literal

from server.brain.llm_clients import ChatMessage

if TYPE_CHECKING:
    from server.observability.telemetry import ProviderCallSpan, SessionTelemetry

logger = logging.getLogger(__name__)

_STREAM_END = object()
_STREAM_QUEUE_SIZE = 8


@dataclass(frozen=True, slots=True)
class _StreamFailure:
    error: Exception


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


class OpenAiCompatibleLlmClient:
    """Minimal client for OpenAI-compatible Chat Completions or Responses.

    Reads credentials from environment variables (never hardcoded, per
    security rules): VOICEAGENT_LLM_API_KEY (required),
    VOICEAGENT_LLM_BASE_URL (default "https://api.openai.com/v1"),
    VOICEAGENT_LLM_MODEL (default "gpt-4o-mini"), and
    VOICEAGENT_LLM_DISABLE_THINKING (default unset — thinking left at the
    provider's default) when `disable_thinking` isn't passed explicitly.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        disable_thinking: bool | None = None,
        api_style: Literal["chat_completions", "responses"] = "chat_completions",
        response_schema: Mapping[str, Any] | None = None,
        response_schema_name: str = "structured_response",
        timeout_s: float = 15.0,
        telemetry: SessionTelemetry | None = None,
        provider_name: str = "openai-compatible",
    ) -> None:
        if not provider_name:
            raise ValueError("provider_name must be non-empty")
        if api_style not in {"chat_completions", "responses"}:
            raise ValueError("api_style must be chat_completions or responses")
        if not response_schema_name:
            raise ValueError("response_schema_name must be non-empty")
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
        self._api_style = api_style
        self._response_schema = (
            json.loads(json.dumps(response_schema))
            if response_schema is not None
            else None
        )
        self._response_schema_name = response_schema_name
        self._timeout_s = timeout_s
        self._telemetry = telemetry
        self._provider_name = provider_name

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        # Reuse the cancellation-aware streaming path even for callers that
        # need one final string. Cancelling a semantic EOT/interruption task
        # now closes the underlying HTTP response instead of leaving an
        # uncancellable urllib worker running until its socket timeout.
        return "".join(
            [
                chunk
                async for chunk in self.stream(
                    system_prompt=system_prompt,
                    user_text=user_text,
                )
            ]
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
    ) -> AsyncIterator[str]:
        async for chunk in self.stream_messages(
            messages=(
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_text),
            )
        ):
            yield chunk

    async def stream_messages(
        self,
        *,
        messages: tuple[ChatMessage, ...],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Expose each provider SSE delta as soon as urllib reads it."""

        if not messages:
            raise ValueError("messages must be non-empty")
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be positive when provided")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | _StreamFailure | object] = asyncio.Queue(
            maxsize=_STREAM_QUEUE_SIZE
        )
        stopped = threading.Event()
        response_lock = threading.Lock()
        response_holder: list[HTTPResponse] = []

        def register_response(response: HTTPResponse) -> None:
            with response_lock:
                response_holder.append(response)
            if stopped.is_set():
                close = getattr(response, "close", None)
                if close is not None:
                    close()

        def emit(item: str | _StreamFailure | object) -> bool:
            future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            while True:
                try:
                    future.result(timeout=0.05)
                    return True
                except FutureTimeoutError:
                    if stopped.is_set():
                        future.cancel()
                        return False

        def produce() -> None:
            iterator = self._stream_sync(
                messages,
                max_tokens=max_tokens,
                on_response=register_response,
            )
            try:
                for chunk in iterator:
                    if stopped.is_set() or not emit(chunk):
                        return
            except Exception as error:  # noqa: BLE001 — forwarded across thread boundary
                if not stopped.is_set():
                    emit(_StreamFailure(error))
                return
            finally:
                iterator.close()
            if not stopped.is_set():
                emit(_STREAM_END)

        provider_scope = (
            self._telemetry.provider_call(
                provider=self._provider_name,
                operation=(
                    "responses.stream"
                    if self._api_style == "responses"
                    else "chat.stream"
                ),
                model=self._model,
                timeout_ms=self._timeout_s * 1000,
            )
            if self._telemetry is not None
            else _noop_provider_call()
        )
        async with provider_scope as provider_call:
            producer = asyncio.create_task(asyncio.to_thread(produce))
            try:
                while True:
                    item = await queue.get()
                    if item is _STREAM_END:
                        await producer
                        return
                    if isinstance(item, _StreamFailure):
                        raise item.error
                    assert isinstance(item, str)
                    if provider_call is not None:
                        provider_call.mark_first_response()
                    yield item
            finally:
                stopped.set()
                with response_lock:
                    response = response_holder[-1] if response_holder else None
                close = getattr(response, "close", None)
                if close is not None:
                    # HTTPResponse.close() may block on a provider socket. It
                    # must never extend the caller's cancellation deadline.
                    loop.run_in_executor(None, close)
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)

    def _stream_sync(
        self,
        messages: tuple[ChatMessage, ...],
        *,
        max_tokens: int | None = None,
        on_response: Callable[[HTTPResponse], None] | None = None,
    ) -> Iterator[str]:
        body_dict, endpoint = self._request_payload(messages, max_tokens=max_tokens)
        body = json.dumps(body_dict).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/{endpoint}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        started_at = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                if on_response is not None:
                    on_response(response)
                yield from self._iter_sse_content(response, api_style=self._api_style)
        except TimeoutError:
            logger.warning(
                "LLM request to %s timed out after %.1fms (timeout_s=%s)",
                self._base_url,
                (time.monotonic() - started_at) * 1000,
                self._timeout_s,
            )
            raise
        except urllib.error.URLError:
            logger.exception(
                "LLM request to %s failed after %.1fms",
                self._base_url,
                (time.monotonic() - started_at) * 1000,
            )
            raise
        duration_ms = (time.monotonic() - started_at) * 1000
        logger.info("LLM request to %s completed in %.1fms", self._base_url, duration_ms)

    def _request_payload(
        self,
        messages: tuple[ChatMessage, ...],
        *,
        max_tokens: int | None,
    ) -> tuple[dict[str, Any], str]:
        if self._api_style == "chat_completions":
            body: dict[str, Any] = {
                "model": self._model,
                "stream": True,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
            }
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
            if self._disable_thinking:
                body["thinking"] = {"type": "disabled"}
            return body, "chat/completions"

        instructions = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        body = {
            "model": self._model,
            "stream": True,
            "input": [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role != "system"
            ],
        }
        if instructions:
            body["instructions"] = instructions
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        if self._disable_thinking:
            body["reasoning"] = {"effort": "none"}
        if self._response_schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": self._response_schema_name,
                    "schema": self._response_schema,
                }
            }
        return body, "responses"

    @staticmethod
    def _read_sse_content(response: HTTPResponse) -> str:
        """Accumulate `delta.content` chunks from an OpenAI-style SSE stream."""
        return "".join(OpenAiCompatibleLlmClient._iter_sse_content(response))

    @staticmethod
    def _iter_sse_content(
        response: HTTPResponse,
        *,
        api_style: Literal["chat_completions", "responses"] = "chat_completions",
    ) -> Iterator[str]:
        """Yield `delta.content` chunks from an OpenAI-style SSE stream."""

        emitted_responses_text = False
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            event = json.loads(payload)
            if api_style == "responses":
                if event.get("type") == "response.output_text.delta":
                    content = event.get("delta")
                    if content:
                        emitted_responses_text = True
                        yield content
                if event.get("type") == "response.failed":
                    response_payload = event.get("response") or {}
                    raise RuntimeError(
                        f"Responses API failed: {response_payload.get('error')}"
                    )
                if event.get("type") == "response.incomplete":
                    response_payload = event.get("response") or {}
                    raise RuntimeError(
                        "Responses API incomplete: "
                        f"{response_payload.get('incomplete_details')}"
                    )
                if (
                    event.get("type") == "response.completed"
                    and not emitted_responses_text
                ):
                    response_payload = event.get("response") or {}
                    for output in response_payload.get("output") or []:
                        for part in output.get("content") or []:
                            content = part.get("text")
                            if part.get("type") == "output_text" and content:
                                emitted_responses_text = True
                                yield content
                continue
            delta = event["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                yield content


@asynccontextmanager
async def _noop_provider_call() -> AsyncIterator[ProviderCallSpan | None]:
    yield None
