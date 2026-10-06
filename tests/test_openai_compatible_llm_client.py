import asyncio
import json
import threading
import time
from typing import Self

import pytest

from server.brain.llm_clients import ChatMessage
from server.brain.plugins import openai_compatible_llm_client as module
from server.brain.plugins.openai_compatible_llm_client import OpenAiCompatibleLlmClient
from server.observability.telemetry import (
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryKind,
)


class _FakeStreamResponse:
    """Iterates raw SSE lines, mirroring how urllib.request's HTTPResponse
    behaves when iterated directly (one line per iteration, bytes)."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


class _BlockingStreamResponse(_FakeStreamResponse):
    def __init__(self) -> None:
        super().__init__([])
        self.waiting = threading.Event()
        self.closed = threading.Event()

    def __iter__(self):
        yield _sse_delta_line("first")
        self.waiting.set()
        self.closed.wait(timeout=2.0)

    def close(self) -> None:
        self.closed.set()


class _SlowCloseStreamResponse(_BlockingStreamResponse):
    def close(self) -> None:
        time.sleep(0.5)
        super().close()


def _sse_delta_line(content: str) -> bytes:
    event = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(event)}".encode()


def _sse_lines_for_content(content: str) -> list[bytes]:
    return [_sse_delta_line(content), b"data: [DONE]"]


def _responses_sse_delta_line(content: str) -> bytes:
    event = {"type": "response.output_text.delta", "delta": content}
    return f"data: {json.dumps(event)}".encode()


def _install_fake_urlopen(monkeypatch, content: str, *, captured: list, timeout_error: bool = False):
    def fake_urlopen(request, timeout=None):
        captured.append({"request": request, "timeout": timeout})
        if timeout_error:
            raise TimeoutError("timed out")
        return _FakeStreamResponse(_sse_lines_for_content(content))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)


def _client(**overrides) -> OpenAiCompatibleLlmClient:
    kwargs = {"api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model"}
    kwargs.update(overrides)
    return OpenAiCompatibleLlmClient(**kwargs)


async def test_reads_credentials_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")
    monkeypatch.setenv("VOICEAGENT_LLM_BASE_URL", "https://env.example/v1/")
    monkeypatch.setenv("VOICEAGENT_LLM_MODEL", "env-model")
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)

    client = OpenAiCompatibleLlmClient()
    result = await client.complete(system_prompt="s", user_text="hello")

    assert result == "hi"
    request = captured[0]["request"]
    assert request.full_url == "https://env.example/v1/chat/completions"
    body = json.loads(request.data)
    assert body["model"] == "env-model"
    assert request.headers["Authorization"] == "Bearer env-key"


async def test_request_always_sets_stream_true(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello")

    body = json.loads(captured[0]["request"].data)
    assert body["stream"] is True


async def test_stream_yields_each_sse_delta_without_waiting_for_completion(monkeypatch):
    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append({"request": request, "timeout": timeout})
        return _FakeStreamResponse(
            [_sse_delta_line("你"), _sse_delta_line("好"), b"data: [DONE]"]
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    chunks = [
        chunk
        async for chunk in _client().stream(system_prompt="s", user_text="hello")
    ]

    assert chunks == ["你", "好"]


async def test_stream_records_provider_total_and_first_token_latency(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-llm",
            thread_id="voice-llm",
        )
    )
    telemetry.record("turn.started", generation=3)
    client = _client(telemetry=telemetry, provider_name="deepseek",
                     instance_id="instance-id", config_version="config-revision")

    assert await client.complete(system_prompt="s", user_text="hello") == "hi"
    await runtime.flush()

    detail = await store.session_detail("voice-llm")

    assert detail is not None
    provider_call = detail.events[-1]
    assert provider_call.name == "provider.deepseek.chat.stream"
    assert provider_call.kind is TelemetryKind.PROVIDER_CALL
    assert provider_call.attributes["ttfb_ms"] is not None
    assert provider_call.attributes["model"] == "test-model"
    first_text = [event for event in detail.events if event.name == "llm.request_to_first_text"]
    assert len(first_text) == 1
    assert first_text[0].duration_ms is not None and first_text[0].duration_ms >= 0
    assert first_text[0].kind is TelemetryKind.SPAN
    assert first_text[0].attributes == {"provider": "deepseek", "model": "test-model",
                                        "instance_id": "instance-id", "config_version": "config-revision"}

    await runtime.close()


async def test_cancelling_a_pending_stream_read_closes_the_http_response(monkeypatch):
    response = _BlockingStreamResponse()
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout=None: response,
    )
    stream = _client().stream(system_prompt="s", user_text="hello")

    assert await anext(stream) == "first"
    pending = asyncio.create_task(anext(stream))
    assert await asyncio.to_thread(response.waiting.wait, 0.5)

    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)

    assert response.closed.wait(timeout=0.2)


async def test_cancelling_complete_closes_the_http_response(monkeypatch):
    response = _BlockingStreamResponse()
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout=None: response,
    )
    pending = asyncio.create_task(
        _client().complete(system_prompt="s", user_text="hello")
    )
    assert await asyncio.to_thread(response.waiting.wait, 0.5)

    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)

    assert response.closed.wait(timeout=0.2)


async def test_cancellation_does_not_confirm_before_blocking_http_close_finishes(monkeypatch):
    response = _SlowCloseStreamResponse()
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout=None: response,
    )
    stream = _client().stream(system_prompt="s", user_text="hello")

    assert await anext(stream) == "first"
    pending = asyncio.create_task(anext(stream))
    assert await asyncio.to_thread(response.waiting.wait, 0.5)

    pending.cancel()
    done, _ = await asyncio.wait({pending}, timeout=0.1)
    assert not done
    assert not response.closed.is_set()
    await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), timeout=1)
    assert response.closed.is_set()


async def test_sends_expected_system_and_user_messages(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi there", captured=captured)
    client = _client()

    result = await client.complete(system_prompt="be helpful", user_text="what time is it?")

    assert result == "hi there"
    body = json.loads(captured[0]["request"].data)
    assert body["messages"] == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "what time is it?"},
    ]


async def test_stream_messages_preserves_prefix_order_and_output_limit(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "{}", captured=captured)
    client = _client()
    messages = (
        ChatMessage(role="system", content="fixed"),
        ChatMessage(role="user", content="history-user"),
        ChatMessage(role="assistant", content="history-assistant"),
        ChatMessage(role="user", content="current"),
    )

    chunks = [
        chunk
        async for chunk in client.stream_messages(messages=messages, max_tokens=64)
    ]

    assert chunks == ["{}"]
    body = json.loads(captured[0]["request"].data)
    assert body["messages"] == [
        {"role": message.role, "content": message.content}
        for message in messages
    ]
    assert body["max_tokens"] == 64


async def test_responses_style_streams_structured_output_with_stable_history(monkeypatch):
    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append({"request": request, "timeout": timeout})
        return _FakeStreamResponse(
            [
                _responses_sse_delta_line('{"status":"complete",'),
                _responses_sse_delta_line('"confidence":0.9,"wait_ms":0}'),
                b'data: {"type":"response.completed"}',
            ]
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    client = _client(
        api_style="responses",
        response_schema=schema,
        response_schema_name="eot_result",
        disable_thinking=True,
    )
    messages = (
        ChatMessage(role="system", content="fixed instruction"),
        ChatMessage(role="assistant", content="你想去哪里？"),
        ChatMessage(role="user", content="北京"),
    )

    result = "".join(
        [
            chunk
            async for chunk in client.stream_messages(
                messages=messages,
                max_tokens=48,
            )
        ]
    )

    assert json.loads(result)["status"] == "complete"
    request = captured[0]["request"]
    body = json.loads(request.data)
    assert request.full_url == "https://example.test/v1/responses"
    assert body["instructions"] == "fixed instruction"
    assert body["input"] == [
        {"role": "assistant", "content": "你想去哪里？"},
        {"role": "user", "content": "北京"},
    ]
    assert body["max_output_tokens"] == 48
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "eot_result",
        "schema": schema,
    }


async def test_responses_style_recovers_text_from_completed_event_without_deltas(
    monkeypatch,
):
    completed = {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"status":"complete","confidence":0.9,"wait_ms":0}',
                        }
                    ]
                }
            ],
        },
    }

    def fake_urlopen(request, timeout=None):
        return _FakeStreamResponse(
            [f"data: {json.dumps(completed)}".encode(), b"data: [DONE]"]
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client(api_style="responses")

    result = await client.complete(system_prompt="judge", user_text="天气怎么样")

    assert result == '{"status":"complete","confidence":0.9,"wait_ms":0}'


async def test_responses_style_surfaces_incomplete_terminal_event(monkeypatch):
    incomplete = {
        "type": "response.incomplete",
        "response": {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        },
    }

    def fake_urlopen(request, timeout=None):
        return _FakeStreamResponse(
            [f"data: {json.dumps(incomplete)}".encode(), b"data: [DONE]"]
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client(api_style="responses")

    with pytest.raises(RuntimeError, match="max_output_tokens"):
        await client.complete(system_prompt="judge", user_text="天气怎么样")


async def test_sends_thinking_disabled_when_constructor_flag_set(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)
    client = _client(disable_thinking=True)

    await client.complete(system_prompt="s", user_text="hello")

    body = json.loads(captured[0]["request"].data)
    assert body["thinking"] == {"type": "disabled"}


async def test_sends_thinking_disabled_when_env_var_set(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_DISABLE_THINKING", "1")
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello")

    body = json.loads(captured[0]["request"].data)
    assert body["thinking"] == {"type": "disabled"}


async def test_omits_thinking_key_by_default(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello")

    body = json.loads(captured[0]["request"].data)
    assert "thinking" not in body


async def test_propagates_timeout_error(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, "hi", captured=captured, timeout_error=True)
    client = _client(timeout_s=0.01)

    with pytest.raises(TimeoutError):
        await client.complete(system_prompt="s", user_text="hi")
