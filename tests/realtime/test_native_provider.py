from __future__ import annotations

import json

from server.realtime.native import OpenAiRealtimeProvider
from server.tools.clock_source import ClockToolSource
from server.tools.registry import ToolRegistry


class FakeConnection:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.messages.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


async def test_openai_native_provider_disables_provider_owned_response_control(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    opened_urls: list[str] = []

    async def fake_connect(url, **kwargs):
        opened_urls.append(url)
        assert kwargs["additional_headers"] == {"Authorization": "Bearer secret"}
        return connection

    monkeypatch.setattr("server.realtime.native.provider.connect", fake_connect)
    provider = OpenAiRealtimeProvider(
        api_key="secret",
        model="gpt-realtime",
        session={
            "instructions": "保持简洁",
            "audio": {
                "input": {
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": "high",
                        "create_response": True,
                        "interrupt_response": True,
                    }
                }
            },
        },
    )

    session = await provider.open(context=None, profile=None)  # type: ignore[arg-type]

    assert opened_urls == [
        "wss://api.openai.com/v1/realtime?model=gpt-realtime"
    ]
    update = json.loads(connection.messages[0])
    assert update["type"] == "session.update"
    assert update["session"]["type"] == "realtime"
    assert update["session"]["instructions"] == "保持简洁"
    audio_input = update["session"]["audio"]["input"]
    assert audio_input["transcription"] == {"model": "gpt-4o-mini-transcribe"}
    assert audio_input["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "high",
        "create_response": False,
        "interrupt_response": False,
    }
    await session.close()


async def test_openai_native_provider_declares_canonical_tools(monkeypatch) -> None:
    connection = FakeConnection()

    async def fake_connect(url, **kwargs):
        del url, kwargs
        return connection

    monkeypatch.setattr("server.realtime.native.provider.connect", fake_connect)
    provider = OpenAiRealtimeProvider(
        api_key="secret",
        model="gpt-realtime",
        tools=ToolRegistry([ClockToolSource()]),
    )

    session = await provider.open(context=None, profile=None)  # type: ignore[arg-type]

    update = json.loads(connection.messages[0])
    assert update["session"]["tools"] == [
        {
            "type": "function",
            "name": "get_current_datetime",
            "description": "Get the authoritative current time and a target "
            "calendar date in an IANA timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, for example Asia/Shanghai",
                    },
                    "day_offset": {
                        "type": "integer",
                        "description": "Calendar-day offset in the target timezone",
                        "minimum": -7,
                        "maximum": 7,
                    },
                },
            },
        }
    ]
    await session.close()
