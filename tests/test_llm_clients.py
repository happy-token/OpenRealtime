"""Tests for OpenAiCompatibleLlmClient — the real, network-calling LLM
conformer. No real network: urllib.request.urlopen is monkeypatched, mirroring
this project's existing test-double pattern for other real conformers.
"""

from __future__ import annotations

import json
from typing import Self

import pytest

from server.brain.plugins import openai_compatible_llm_client
from server.brain.plugins.openai_compatible_llm_client import OpenAiCompatibleLlmClient


class FakeSseResponse:
    """Test double for an OpenAI-style SSE `text/event-stream` response.

    Iterating yields one `data: {...}` line per content chunk, terminated by
    `data: [DONE]`, mirroring what `urllib.request.urlopen`'s response object
    yields when iterated line-by-line for a real streamed reply.
    """

    def __init__(self, content_chunks: list[str]) -> None:
        lines = [
            f"data:{json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n".encode()
            for chunk in content_chunks
        ]
        lines.append(b"data:[DONE]\n")
        self._lines = lines

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_constructor_uses_explicit_api_key_over_env_var(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")

    client = OpenAiCompatibleLlmClient(api_key="explicit-key")

    assert client._api_key == "explicit-key"


def test_constructor_falls_back_to_env_var_api_key(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")

    client = OpenAiCompatibleLlmClient()

    assert client._api_key == "env-key"


def test_constructor_raises_when_api_key_missing_everywhere(monkeypatch):
    monkeypatch.delenv("VOICEAGENT_LLM_API_KEY", raising=False)

    with pytest.raises(KeyError):
        OpenAiCompatibleLlmClient()


def test_constructor_defaults_base_url_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")

    client = OpenAiCompatibleLlmClient(base_url="https://example.com/v1/")

    assert client._base_url == "https://example.com/v1"


def test_constructor_defaults_model_to_gpt_4o_mini(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "env-key")

    client = OpenAiCompatibleLlmClient()

    assert client._model == "gpt-4o-mini"


async def test_complete_posts_expected_request_and_parses_reply(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeSseResponse(["hi there"])

    monkeypatch.setattr(openai_compatible_llm_client.urllib.request, "urlopen", fake_urlopen)
    client = OpenAiCompatibleLlmClient(
        api_key="secret", base_url="https://example.com/v1", model="test-model"
    )

    reply = await client.complete(system_prompt="be nice", user_text="hello")

    assert reply == "hi there"
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["body"] == {
        "model": "test-model",
        "stream": True,
        "messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hello"},
        ],
    }


async def test_complete_accumulates_multiple_sse_chunks(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeSseResponse(["hi", " ", "there"])

    monkeypatch.setattr(openai_compatible_llm_client.urllib.request, "urlopen", fake_urlopen)
    client = OpenAiCompatibleLlmClient(api_key="secret")

    reply = await client.complete(system_prompt="s", user_text="u")

    assert reply == "hi there"


async def test_complete_uses_configured_timeout(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        return FakeSseResponse(["ok"])

    monkeypatch.setattr(openai_compatible_llm_client.urllib.request, "urlopen", fake_urlopen)
    client = OpenAiCompatibleLlmClient(api_key="secret", timeout_s=5.0)

    await client.complete(system_prompt="s", user_text="u")

    assert captured["timeout"] == 5.0
