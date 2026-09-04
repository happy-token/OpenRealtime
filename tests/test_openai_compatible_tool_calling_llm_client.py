import asyncio
import json
import threading
from typing import Any, Self

import pytest

from server.brain.llm_clients import FinalText, ToolCallRequest
from server.brain.plugins import openai_compatible_tool_calling_llm_client as module
from server.brain.plugins.openai_compatible_tool_calling_llm_client import (
    OpenAiCompatibleToolCallingLlmClient,
)
from server.tools.canonical import CanonicalTool


async def _unused_handler(arguments: dict) -> str:
    return "unused"


def _clock_tool() -> CanonicalTool:
    return CanonicalTool(
        name="get_current_datetime",
        description="Get the current date and time",
        parameters={"type": "object", "properties": {}},
        handler=_unused_handler,
    )


def _search_tool() -> CanonicalTool:
    return CanonicalTool(
        name="search_web",
        description="Search the web",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_unused_handler,
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


def _sse_delta_line(delta: dict[str, Any]) -> bytes:
    event = {"choices": [{"delta": delta}]}
    return f"data: {json.dumps(event)}".encode()


def _sse_lines_for_message(message: dict[str, Any]) -> list[bytes]:
    """Converts a non-streaming OpenAI-style `message` dict (the shape this
    client's callers/tests reasoned about before ADR-0033) into the
    equivalent SSE delta stream this client now actually parses."""
    lines: list[bytes] = []
    content = message.get("content")
    if content:
        lines.append(_sse_delta_line({"content": content}))
    for index, tool_call in enumerate(message.get("tool_calls") or []):
        function = tool_call["function"]
        lines.append(
            _sse_delta_line(
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": tool_call.get("id"),
                            "type": "function",
                            "function": {"name": function["name"], "arguments": ""},
                        }
                    ]
                }
            )
        )
        lines.append(
            _sse_delta_line(
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "function": {"arguments": function.get("arguments") or "{}"},
                        }
                    ]
                }
            )
        )
    lines.append(b"data: [DONE]")
    return lines


def _install_fake_urlopen(
    monkeypatch,
    message: dict,
    *,
    captured: list,
    timeout_error: bool = False,
):
    def fake_urlopen(request, timeout=None):
        captured.append({"request": request, "timeout": timeout})
        if timeout_error:
            raise TimeoutError("timed out")
        return _FakeStreamResponse(_sse_lines_for_message(message))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)


def _client(**overrides) -> OpenAiCompatibleToolCallingLlmClient:
    kwargs = {"api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model"}
    kwargs.update(overrides)
    return OpenAiCompatibleToolCallingLlmClient(**kwargs)


async def test_reads_credentials_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")
    monkeypatch.setenv("VOICEAGENT_LLM_BASE_URL", "https://env.example/v1/")
    monkeypatch.setenv("VOICEAGENT_LLM_MODEL", "env-model")
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)

    client = OpenAiCompatibleToolCallingLlmClient()
    await client.complete(system_prompt="s", user_text="hello", tools=[])

    request = captured[0]["request"]
    assert request.full_url == "https://env.example/v1/chat/completions"
    body = json.loads(request.data)
    assert body["model"] == "env-model"
    assert request.headers["Authorization"] == "Bearer env-key"


async def test_request_always_sets_stream_true(monkeypatch):
    """ADR-0033: the Bella gateway 400s any /chat/completions call that omits
    this, even for this client's conceptually-non-streaming tool-call flow."""
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello", tools=[])

    body = json.loads(captured[0]["request"].data)
    assert body["stream"] is True


async def test_first_call_sends_system_and_user_messages_plus_tool_schema(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi there"}, captured=captured)
    client = _client()

    result = await client.complete(
        system_prompt="be helpful", user_text="what time is it?", tools=[_clock_tool()]
    )

    assert result == FinalText("hi there")
    body = json.loads(captured[0]["request"].data)
    assert body["messages"] == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "what time is it?"},
    ]
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_current_datetime",
                "description": "Get the current date and time",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert body["parallel_tool_calls"] is False


async def test_omits_tools_key_when_no_tools_available(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello", tools=[])

    body = json.loads(captured[0]["request"].data)
    assert "tools" not in body


async def test_parses_tool_call_response_into_tool_call_request(monkeypatch):
    captured: list = []
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    _install_fake_urlopen(monkeypatch, message, captured=captured)
    client = _client()

    result = await client.complete(
        system_prompt="s", user_text="what time is it?", tools=[_clock_tool()]
    )

    assert result == ToolCallRequest(name="get_current_datetime", arguments={})


async def test_concurrent_turns_keep_tool_call_state_isolated(monkeypatch):
    """A cancelled provider thread from one turn must not corrupt the next turn."""
    first_request_started = threading.Event()
    release_first_request = threading.Event()

    def fake_urlopen(request, timeout=None):
        del timeout
        body = json.loads(request.data)
        user_text = body["messages"][1]["content"]
        if user_text == "明天天气":
            first_request_started.set()
            assert release_first_request.wait(timeout=1)
            return _FakeStreamResponse(
                _sse_lines_for_message(
                    {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_weather_1",
                                "type": "function",
                                "function": {
                                    "name": "search_web",
                                    "arguments": '{"query":"明天天气"}',
                                },
                            }
                        ],
                    }
                )
            )
        return _FakeStreamResponse(
            _sse_lines_for_message({"content": "请告诉我想查询的城市。"})
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()
    tools = [_search_tool()]

    first = asyncio.create_task(
        client.complete(
            system_prompt="s",
            user_text="明天天气",
            tools=tools,
        )
    )
    assert await asyncio.to_thread(first_request_started.wait, 1)

    second = await client.complete(
        system_prompt="s",
        user_text="明天天气怎么样？",
        tools=tools,
    )
    release_first_request.set()
    first_result = await first

    assert second == FinalText("请告诉我想查询的城市。")
    assert first_result == ToolCallRequest(
        name="search_web",
        arguments={"query": "明天天气"},
    )


async def test_accumulates_tool_call_arguments_split_across_stream_chunks(monkeypatch):
    """A real streaming provider fragments `arguments` across many chunks —
    this asserts the accumulation actually concatenates rather than
    overwriting, since the fixture above only ever sends one chunk."""
    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        lines = [
            _sse_delta_line(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": "get_current_datetime", "arguments": ""},
                        }
                    ]
                }
            ),
            _sse_delta_line(
                {"tool_calls": [{"index": 0, "function": {"arguments": "{\"tz\""}}]}
            ),
            _sse_delta_line(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": ": \"UTC\"}"}}
                    ]
                }
            ),
            b"data: [DONE]",
        ]
        return _FakeStreamResponse(lines)

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()

    result = await client.complete(
        system_prompt="s", user_text="what time is it?", tools=[_clock_tool()]
    )

    assert result == ToolCallRequest(name="get_current_datetime", arguments={"tz": "UTC"})


async def test_uses_first_tool_call_and_warns_when_provider_ignores_serial_mode(
    monkeypatch, caplog
):
    captured: list = []
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "search_web", "arguments": "{}"},
            },
        ],
    }
    _install_fake_urlopen(monkeypatch, message, captured=captured)
    client = _client()

    tools = [
        _clock_tool(),
        CanonicalTool(
            name="search_web",
            description="search",
            parameters={"type": "object", "properties": {}},
            handler=_unused_handler,
        ),
    ]
    with caplog.at_level("WARNING"):
        result = await client.complete(system_prompt="s", user_text="hi", tools=tools)

    assert result == ToolCallRequest(name="get_current_datetime", arguments={})
    assert "using the first sequentially" in caplog.text


async def test_prioritizes_search_when_weather_plan_contains_clock_and_search(
    monkeypatch, caplog
):
    captured: list = []
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_clock",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            },
            {
                "id": "call_search",
                "type": "function",
                "function": {
                    "name": "search_web",
                    "arguments": '{"query":"今天上海天气"}',
                },
            },
        ],
    }
    _install_fake_urlopen(monkeypatch, message, captured=captured)
    client = _client()

    with caplog.at_level("WARNING"):
        result = await client.complete(
            system_prompt="s",
            user_text="今天上海天气怎么样？",
            tools=[_clock_tool(), _search_tool()],
        )

    assert result == ToolCallRequest(
        name="search_web",
        arguments={"query": "今天上海天气"},
    )
    assert "prioritizing search_web" in caplog.text


async def test_tool_result_follow_up_replays_pending_tool_call(monkeypatch):
    captured: list = []
    first_message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_xyz",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    second_message = {"content": "It is noon."}
    responses = [first_message, second_message]

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        return _FakeStreamResponse(_sse_lines_for_message(responses[len(captured) - 1]))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()

    first_result = await client.complete(
        system_prompt="s", user_text="what time is it?", tools=[_clock_tool()]
    )
    assert first_result == ToolCallRequest(name="get_current_datetime", arguments={})

    second_result = await client.complete(
        system_prompt="s",
        user_text="what time is it?",
        tools=[_clock_tool()],
        tool_result="2026-08-04T12:00:00+08:00",
    )

    assert second_result == FinalText("It is noon.")
    second_body = json.loads(captured[1].data)
    assert second_body["messages"][2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_xyz",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    assert second_body["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_xyz",
        "content": "2026-08-04T12:00:00+08:00",
    }


async def test_parses_deepseek_dsml_follow_up_as_tool_call_instead_of_final_text(
    monkeypatch,
):
    """DeepSeek may serialize a follow-up tool call into content as DSML."""
    first_message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_clock",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    dsml = """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="search_web">
<｜｜DSML｜｜parameter name="query" string="true">今天上海天气2026年8月16日</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""
    responses = [
        first_message,
        {"content": dsml},
        {"content": "上海今天有阵雨，出门记得带伞。"},
    ]
    captured: list = []

    def fake_urlopen(request, timeout=None):
        del timeout
        captured.append(request)
        return _FakeStreamResponse(_sse_lines_for_message(responses[len(captured) - 1]))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()
    tools = [_clock_tool(), _search_tool()]

    first_result = await client.complete(
        system_prompt="s", user_text="今天天气怎么样", tools=tools
    )
    assert first_result == ToolCallRequest(name="get_current_datetime", arguments={})

    second_result = await client.complete(
        system_prompt="s",
        user_text="今天天气怎么样",
        tools=tools,
        tool_result="2026-08-16T09:54:00+08:00",
    )

    assert second_result == ToolCallRequest(
        name="search_web",
        arguments={"query": "今天上海天气2026年8月16日"},
    )
    second_body = json.loads(captured[1].data)
    assert "tools" in second_body
    assert second_body["parallel_tool_calls"] is False

    final_result = await client.complete(
        system_prompt="s",
        user_text="今天天气怎么样",
        tools=tools,
        tool_result="上海：阵雨，30℃",
    )

    assert final_result == FinalText("上海今天有阵雨，出门记得带伞。")
    final_body = json.loads(captured[2].data)
    assert [message["role"] for message in final_body["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert "DSML" not in final_result.text


async def test_rejects_malformed_dsml_instead_of_returning_speakable_text(monkeypatch):
    captured: list = []
    _install_fake_urlopen(
        monkeypatch,
        {"content": "<｜｜DSML｜｜tool_calls>broken"},
        captured=captured,
    )
    client = _client()

    with pytest.raises(RuntimeError, match="malformed DeepSeek DSML"):
        await client.complete(
            system_prompt="s",
            user_text="今天天气怎么样",
            tools=[_search_tool()],
        )


async def test_keeps_tools_available_on_tool_result_follow_up(monkeypatch):
    first_message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_xyz",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    second_message = {"content": "It is noon."}
    responses = [first_message, second_message]
    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        return _FakeStreamResponse(_sse_lines_for_message(responses[len(captured) - 1]))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()

    await client.complete(system_prompt="s", user_text="what time is it?", tools=[_clock_tool()])
    await client.complete(
        system_prompt="s",
        user_text="what time is it?",
        tools=[_clock_tool()],
        tool_result="2026-08-04T12:00:00+08:00",
    )

    first_body = json.loads(captured[0].data)
    second_body = json.loads(captured[1].data)
    assert "tools" in first_body
    assert first_body["parallel_tool_calls"] is False
    assert second_body["tools"] == first_body["tools"]
    assert second_body["parallel_tool_calls"] is False


async def test_rejects_tool_result_when_no_pending_call_exists(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client()

    with pytest.raises(RuntimeError, match="no pending tool turn"):
        await client.complete(system_prompt="s", user_text="hi", tools=[], tool_result="12:00")


async def test_returns_second_sequential_tool_call_on_follow_up(monkeypatch):
    tool_call_message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": "{}"},
            }
        ],
    }
    responses = [tool_call_message, tool_call_message]
    captured: list = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        return _FakeStreamResponse(_sse_lines_for_message(responses[len(captured) - 1]))

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    client = _client()

    tools = [_clock_tool()]
    await client.complete(system_prompt="s", user_text="hi", tools=tools)

    result = await client.complete(
        system_prompt="s", user_text="hi", tools=tools, tool_result="result"
    )

    assert result == ToolCallRequest(name="get_current_datetime", arguments={})


async def test_sends_thinking_disabled_when_constructor_flag_set(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client(disable_thinking=True)

    await client.complete(system_prompt="s", user_text="hello", tools=[])

    body = json.loads(captured[0]["request"].data)
    assert body["thinking"] == {"type": "disabled"}


async def test_sends_thinking_disabled_when_env_var_set(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_DISABLE_THINKING", "1")
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello", tools=[])

    body = json.loads(captured[0]["request"].data)
    assert body["thinking"] == {"type": "disabled"}


async def test_omits_thinking_key_by_default(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured)
    client = _client()

    await client.complete(system_prompt="s", user_text="hello", tools=[])

    body = json.loads(captured[0]["request"].data)
    assert "thinking" not in body


async def test_propagates_timeout_error(monkeypatch):
    captured: list = []
    _install_fake_urlopen(monkeypatch, {"content": "hi"}, captured=captured, timeout_error=True)
    client = _client(timeout_s=0.01)

    with pytest.raises(TimeoutError):
        await client.complete(system_prompt="s", user_text="hi", tools=[])
