"""Cancellation acknowledgement must include owned provider stream cleanup."""

import asyncio

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.brain import (
    CancelBrainResponse,
    LegacyBrainCapabilityAdapter,
    RequestBrainResponse,
)
from server.realtime.capabilities.brain_streaming import (
    BrainStreamingAdapter,
    VoiceRuntimeBrainStreamingAdapter,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_cascaded_engine import EchoDuplexTts


class GatedProvider:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self.calls = 0

    async def stream(self, turn):
        self.calls += 1
        try:
            yield "首个响应"
            await asyncio.Event().wait()
        finally:
            self.entered.set()
            await self.release.wait()
            self.closed = True


@pytest.mark.parametrize("wrapping", ["bare", "production_miss", "production_hit", "speech_miss", "speech_hit"])
async def test_delta_backpressure_cancellation_waits_for_real_owned_provider_cleanup(wrapping):
    provider = GatedProvider()
    turn = TurnContent(text="你好", generation=1)
    brain = provider
    producer = None
    if wrapping != "bare":
        adapter = BrainStreamingAdapter(provider)
        cache = (SpeculativeSpeechPipeline(brain=adapter, tts=EchoDuplexTts())
                 if wrapping.startswith("speech") else SpeculativeStreamingBrain(adapter))
        brain = VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object())
        if wrapping.endswith("hit"):
            await cache.prepare(turn)
            producer = cache._state.task
            async with asyncio.timeout(.5):
                while not getattr(cache._state, "chunks", getattr(cache._state, "text_chunks", [])):
                    await asyncio.sleep(0)
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    session._events = asyncio.Queue(maxsize=1)
    cancellation = None
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="old", turn=turn))
        async with asyncio.timeout(.5):
            while not session._events._putters:
                await asyncio.sleep(0)
        cancellation = asyncio.create_task(session.send(CancelBrainResponse(
            response_id="same", request_token="old", reason="heard_frontier_changed")))
        await asyncio.wait_for(provider.entered.wait(), .5)
        await asyncio.sleep(.12)
        assert not cancellation.done(), "provider cleanup cannot be acknowledged before it finishes"
        assert "same" in session._requests
        assert not provider.closed
        with pytest.raises(ValueError, match="already active"):
            await session.send(RequestBrainResponse(response_id="same", request_token="new", turn=turn))
        provider.release.set()
        await asyncio.wait_for(cancellation, .5)
        assert provider.closed
        assert provider.calls == 1
        assert not session._requests
    finally:
        provider.release.set()
        if cancellation is not None:
            await asyncio.gather(cancellation, return_exceptions=True)
        if producer is not None:
            await asyncio.gather(producer, return_exceptions=True)
        while not session._events.empty():
            session._events.get_nowait()
        await session.close()


async def test_closing_a_full_queue_handles_provider_which_returns_after_cancellation():
    entered = asyncio.Event()

    class Provider:
        async def stream(self, turn):
            yield "首个响应"
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

    session = await LegacyBrainCapabilityAdapter(Provider()).open(context=context())
    session._events = asyncio.Queue(maxsize=2)
    await session.send(RequestBrainResponse(response_id="same", request_token="old",
                                            turn=TurnContent(text="你好", generation=1)))
    await asyncio.wait_for(entered.wait(), .5)
    assert session._events.full()
    await asyncio.wait_for(session.close(), .5)
    assert not session._requests


@pytest.mark.parametrize("prefetched", [False, True])
async def test_real_chat_sdk_chain_keeps_owner_until_http_and_worker_finish(monkeypatch, prefetched):
    import threading

    from server.brain.chat_brain import ChatBrain
    from server.brain.plugins import openai_compatible_llm_client as module
    from tests.test_openai_compatible_llm_client import _BlockingStreamResponse, _client

    class Response(_BlockingStreamResponse):
        def __init__(self):
            super().__init__()
            self.close_entered = threading.Event()
            self.release_close = threading.Event()
            self.worker_exited = threading.Event()

        def close(self):
            self.close_entered.set()
            assert self.release_close.wait(2)
            super().close()

        def __exit__(self, *exc_info):
            self.worker_exited.set()
            return False

    response = Response()
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: response)
    cache = SpeculativeStreamingBrain(BrainStreamingAdapter(ChatBrain(_client())))
    brain = VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object())
    turn = TurnContent(text="hello", generation=1)
    producer = None
    if prefetched:
        await cache.prepare(turn)
        producer = cache._state.task
        async with asyncio.timeout(1):
            while not getattr(cache._state, "chunks", getattr(cache._state, "text_chunks", [])):
                await asyncio.sleep(.001)
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    session._events = asyncio.Queue(maxsize=1)
    cancellation = None
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="old", turn=turn))
        async with asyncio.timeout(1):
            while not session._events._putters:
                await asyncio.sleep(.001)
        cancellation = asyncio.create_task(session.send(CancelBrainResponse(
            response_id="same", request_token="old", reason="rebuild")))
        assert await asyncio.to_thread(response.close_entered.wait, 1)
        await asyncio.sleep(.12)
        assert not cancellation.done()
        assert not response.closed.is_set() and not response.worker_exited.is_set()
        assert "same" in session._requests
        response.release_close.set()
        await asyncio.wait_for(cancellation, 1)
        assert response.closed.is_set() and response.worker_exited.is_set()
        assert not session._requests
    finally:
        response.release_close.set()
        response.closed.set()
        if cancellation:
            await asyncio.gather(cancellation, return_exceptions=True)
        if producer:
            await asyncio.gather(producer, return_exceptions=True)
        while not session._events.empty():
            session._events.get_nowait()
        await session.close()


async def test_text_audio_provider_cleanup_failure_does_not_acknowledge_cancellation():
    entered = asyncio.Event()

    class BrokenTts:
        async def synthesize_duplex(self, texts):
            try:
                async for text in texts:
                    entered.set()
                    from server.speech.tts import SynthesizedAudioChunk
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                raise RuntimeError("TTS physical cleanup failed")

    provider = GatedProvider()
    provider.release.set()
    cache = SpeculativeSpeechPipeline(brain=BrainStreamingAdapter(provider), tts=BrokenTts())
    turn = TurnContent(text="你好", generation=1)
    await cache.prepare(turn)
    await asyncio.wait_for(entered.wait(), .5)
    session = await LegacyBrainCapabilityAdapter(
        VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object())).open(context=context())
    session._events = asyncio.Queue(maxsize=1)
    await session.send(RequestBrainResponse(response_id="same", request_token="old", turn=turn))
    async with asyncio.timeout(.5):
        while not session._events._putters:
            await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="cleanup was not confirmed"):
        await session.send(CancelBrainResponse(response_id="same", request_token="old", reason="retry"))
    assert "same" in session._requests
    assert not session._requests["same"].cleanup_confirmed
    assert provider.closed
    assert cache._state is None
    with pytest.raises(RuntimeError, match="did not confirm"):
        await session.close()


@pytest.mark.parametrize("phase", ["plan", "follow_up"])
@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_real_tool_sdk_keeps_worker_ownership_during_cancellation(monkeypatch, phase, cancel_waiter):
    import threading

    from server.brain.llm_clients import FinalText, ToolCallRequest
    from server.brain.plugins.openai_compatible_tool_calling_llm_client import (
        OpenAiCompatibleToolCallingLlmClient,
    )
    from server.brain.tool_calling_brain import ToolCallingBrain
    from server.realtime.capabilities.brain import BrainToolRequested, SubmitBrainToolResult
    from server.realtime.capabilities.brain_streaming import ToolCallingBrainStreamingAdapter
    from server.tools.registry import ToolRegistry
    from tests.test_openai_compatible_tool_calling_llm_client import _search_tool

    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    client = OpenAiCompatibleToolCallingLlmClient(api_key="test", base_url="https://example.test", model="test")
    class Source:
        def list_tools(self):
            return [_search_tool()]

    def complete_sync(system, user, tools, result, state):
        if phase == "follow_up" and result is None:
            return ToolCallRequest(name="search_web", arguments={"query": "weather"})
        entered.set()
        try:
            assert release.wait(2)
            return FinalText("天气结果")
        finally:
            exited.set()

    monkeypatch.setattr(client, "_complete_sync", complete_sync)
    tools = ToolCallingBrainStreamingAdapter(ToolCallingBrain(client, ToolRegistry([Source()])))
    brain = VoiceRuntimeBrainStreamingAdapter(chat=object(), tools=tools, slow_tool_ack_delay_s=5)
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    stream = session.events()
    cancellation = None
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="old",
            turn=TurnContent(text="weather", generation=1)))
        if phase == "follow_up":
            async with asyncio.timeout(.5):
                async for event in stream:
                    if isinstance(event, BrainToolRequested):
                        await session.send(SubmitBrainToolResult(response_id="same", request_token="old",
                            call_id=event.call_id, success=True, model_output="tool output"))
                        break
        assert await asyncio.to_thread(entered.wait, .5)
        cancellation = asyncio.create_task(session.send(CancelBrainResponse(
            response_id="same", request_token="old", reason="retry")))
        await asyncio.sleep(.12)
        assert not cancellation.done() and not exited.is_set()
        assert "same" in session._requests
        closing = None
        if cancel_waiter:
            cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)
            assert "same" in session._requests and not exited.is_set()
            first_close = asyncio.create_task(session.close())
            await asyncio.sleep(.01)
            first_close.cancel()
            await asyncio.gather(first_close, return_exceptions=True)
            closing = asyncio.create_task(session.close())
            await asyncio.sleep(.025)
            assert not closing.done()
            assert "same" in session._requests and not exited.is_set()
        release.set()
        await asyncio.wait_for(closing if closing is not None else cancellation, .5)
        assert exited.is_set() and not session._requests
    finally:
        release.set()
        if cancellation:
            await asyncio.gather(cancellation, return_exceptions=True)
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("prefetched", [False, True])
async def test_cancellation_inside_owned_provider_preserves_cleanup_error_and_owner(prefetched):
    entered = asyncio.Event()

    class Provider:
        async def stream(self, turn):
            try:
                yield "首个响应"
                entered.set()
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("provider socket cleanup failed")

    cache = SpeculativeStreamingBrain(BrainStreamingAdapter(Provider()))
    turn = TurnContent(text="你好", generation=1)
    if prefetched:
        await cache.prepare(turn)
    session = await LegacyBrainCapabilityAdapter(
        VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object())).open(context=context())
    await session.send(RequestBrainResponse(response_id="same", request_token="old", turn=turn))
    await asyncio.wait_for(entered.wait(), .5)
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="cleanup was not confirmed.*provider socket cleanup failed"):
        await session.send(CancelBrainResponse(response_id="same", request_token="old", reason="retry"))
    assert "same" in session._requests
    assert not session._requests["same"].cleanup_confirmed
    with pytest.raises(RuntimeError, match="did not confirm.*provider socket cleanup failed"):
        await session.close()


@pytest.mark.parametrize("mode", ["text", "text_audio"])
async def test_ordinary_provider_failure_with_successful_cleanup_releases_owner(mode):
    from server.realtime.capabilities.brain import BrainResponseFailed

    class Brain:
        async def stream(self, turn):
            if mode == "text":
                raise RuntimeError("ordinary provider request failed")
            yield "首个响应"

    class Tts:
        async def synthesize_duplex(self, texts):
            async for text in texts:
                raise RuntimeError("ordinary provider request failed")
                yield None

    cache = (SpeculativeSpeechPipeline(brain=Brain(), tts=Tts()) if mode == "text_audio"
             else SpeculativeStreamingBrain(Brain()))
    turn = TurnContent(text="你好", generation=1)
    await cache.prepare(turn)
    state = cache._state
    await state.task
    assert state.error is not None and state.cleanup_error is None
    session = await LegacyBrainCapabilityAdapter(
        VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object())).open(context=context())
    stream = session.events()
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="old", turn=turn))
        async with asyncio.timeout(.5):
            async for event in stream:
                if isinstance(event, BrainResponseFailed):
                    assert event.error == "ordinary provider request failed"
                    break
        await session.send(CancelBrainResponse(response_id="same", request_token="old", reason="failed"))
        assert not session._requests
        assert not session._closed
    finally:
        await stream.aclose()
        await session.close()
