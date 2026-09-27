from __future__ import annotations

import asyncio
import json

import pytest

from server.speech.plugins.bailian_asr import BailianAsrEngine, BailianAsrSession, realtime_url


def test_workspace_endpoint_is_used_for_realtime_websocket():
    assert realtime_url("https://llm-test.cn-beijing.maas.aliyuncs.com/") == (
        "wss://llm-test.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime"
    )
    for url in ("http://llm-test.cn-beijing.maas.aliyuncs.com",
                "https://evil.example.com", "https://dashscope.aliyuncs.com.evil.example.com",
                "https://dashscope.aliyuncs.com/custom"):
        with pytest.raises(ValueError):
            realtime_url(url)


def test_partial_and_final_events_follow_shared_asr_contract():
    class FakeConnection:
        def __init__(self):
            self.messages = asyncio.Queue()
            self.sent = []

        async def send(self, value):
            self.sent.append(json.loads(value))

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self.messages.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self):
            await self.messages.put(None)

    async def scenario():
        connection = FakeConnection()
        session = BailianAsrSession(connection)
        await session.push_audio(b"\x01\x00" * 1600, sample_rate_hz=16000)
        assert connection.sent[0]["type"] == "input_audio_buffer.append"
        await connection.messages.put({"type": "conversation.item.input_audio_transcription.text",
                                       "text": "你好", "stash": "世界"})
        partial = await asyncio.wait_for(session.wait_for_update(
            after_revision=0, after_sentence_end_revision=0), 1)
        assert partial.text == "你好世界"
        assert not partial.is_sentence_end
        await connection.messages.put({"type": "conversation.item.input_audio_transcription.completed",
                                       "transcript": "你好世界。"})
        final = await asyncio.wait_for(session.wait_for_update(
            after_revision=partial.revision, after_sentence_end_revision=0), 1)
        assert final.text == "你好世界。"
        assert final.is_sentence_end
        assert await session.consume_transcript() == "你好世界。"
        await session.close()
        assert connection.sent[-1]["type"] == "session.finish"

    asyncio.run(scenario())


def test_engine_uses_workspace_base_url(monkeypatch):
    engine = BailianAsrEngine(api_key="secret", base_url="https://llm-test.cn-beijing.maas.aliyuncs.com")
    assert engine._url.startswith("wss://llm-test.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?")
