"""Provider suspension at a full output queue must not escape TTS ownership."""

import asyncio

import pytest

from server.core.async_stream import OwnedStreamCleanupError
from server.realtime.capabilities.tts import (
    AppendTtsText,
    CancelTts,
    CommitTts,
    LegacyTtsCapabilityAdapter,
    StartTts,
    TtsCancelled,
    TtsFailed,
)
from server.speech.tts import SynthesizedAudioChunk
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_input_association_production import wait_for


@pytest.mark.parametrize("duplex", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_full_queue_cancel_closes_actual_provider_before_ack(duplex, cleanup_fails):
    entered, release, closed = (asyncio.Event() for _ in range(3))

    async def generate():
        try:
            for _ in range(128):
                yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
        finally:
            entered.set()
            await release.wait()
            closed.set()
            if cleanup_fails:
                raise RuntimeError("provider socket close failed")

    class Streaming:
        def synthesize_stream(self, text):
            return generate()

    class Duplex:
        async def synthesize_duplex(self, texts):
            await anext(texts)
            try:
                for _ in range(128):
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                entered.set()
                await release.wait()
                closed.set()
                if cleanup_fails:
                    raise RuntimeError("provider socket close failed")

    session = await LegacyTtsCapabilityAdapter(Duplex() if duplex else Streaming(), cancel_timeout_s=.5).open(context=context())
    events = session.events()
    cancellation = None
    try:
        await session.send(StartTts(speech_id="old"))
        await session.send(AppendTtsText(speech_id="old", text_sequence=1, delta="一句话。"))
        await session.send(CommitTts(speech_id="old"))
        await wait_for(lambda: session._events.full())
        cancellation = asyncio.create_task(session.send(CancelTts(speech_id="old", reason="failed")))
        await asyncio.wait_for(entered.wait(), .2)
        assert not cancellation.done() and not closed.is_set()
        cancellation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancellation
        # A second waiter must join rather than cancel an in-flight finally.
        cancellation = asyncio.create_task(session.send(CancelTts(speech_id="old", reason="failed")))
        await asyncio.sleep(0)
        assert not closed.is_set()
        release.set()
        received = []
        async with asyncio.timeout(.5):
            while not any(isinstance(event, (TtsFailed, TtsCancelled)) for event in received):
                received.append(await anext(events))
        assert closed.is_set()
        if cleanup_fails:
            with pytest.raises(OwnedStreamCleanupError, match="provider socket close failed"):
                await cancellation
            failure = received[-1]
            assert isinstance(failure, TtsFailed) and failure.cleanup_failed
            assert not any(isinstance(event, TtsCancelled) for event in received)
            with pytest.raises(RuntimeError, match="requires a new capability session"):
                await session.send(StartTts(speech_id="new"))
        else:
            await cancellation
            assert isinstance(received[-1], TtsCancelled)
            assert not received[-1].cleanup_timed_out
    finally:
        release.set()
        if cancellation is not None:
            await asyncio.gather(cancellation, return_exceptions=True)
        await asyncio.gather(session.close(), return_exceptions=True)


@pytest.mark.parametrize("duplex", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_close_waiters_share_actual_provider_cleanup(duplex, cleanup_fails):
    entered, release, closed = (asyncio.Event() for _ in range(3))
    transport_closes = []

    class Provider:
        async def chunks(self):
            try:
                for _ in range(128):
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                entered.set()
                await release.wait()
                closed.set()
                if cleanup_fails:
                    raise RuntimeError("close socket failed")

        async def close(self):
            assert closed.is_set()
            transport_closes.append(True)

    class Streaming(Provider):
        def synthesize_stream(self, text):
            return self.chunks()

    class Duplex(Provider):
        def synthesize_duplex(self, texts):
            return self.chunks()

    session = await LegacyTtsCapabilityAdapter(Duplex() if duplex else Streaming(), cancel_timeout_s=.01).open(context=context())
    await session.send(StartTts(speech_id="old"))
    await session.send(AppendTtsText(speech_id="old", text_sequence=1, delta="一句话。"))
    await session.send(CommitTts(speech_id="old"))
    await wait_for(lambda: session._events.full())
    first = asyncio.create_task(session.close())
    try:
        await asyncio.wait_for(entered.wait(), .2)
        assert not first.done() and not closed.is_set()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(session.close())
        await asyncio.sleep(0)
        assert not second.done() and not closed.is_set()
        release.set()
        if cleanup_fails:
            with pytest.raises(OwnedStreamCleanupError, match="close socket failed"):
                await second
            with pytest.raises(OwnedStreamCleanupError, match="close socket failed"):
                await session.close()
        else:
            await second
            await session.close()
        assert closed.is_set() and transport_closes == [True]
        assert not session._detached_tasks
    finally:
        release.set()
        await asyncio.gather(session.close(), return_exceptions=True)
