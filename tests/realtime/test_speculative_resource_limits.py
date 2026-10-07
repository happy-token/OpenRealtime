"""Real speculative provider loops, including retirement before replacement."""

import asyncio

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.speech.tts import SynthesizedAudioChunk


class EchoTts:
    async def synthesize_duplex(self, texts):
        async for text in texts:
            yield SynthesizedAudioChunk(pcm16=text.encode(), sample_rate_hz=16000, is_final=False)


async def test_uncommitted_text_cache_rejects_oversized_output_before_retaining_it():
    class Brain:
        async def stream(self, turn):
            yield "x" * (256 * 1024)

    cache = SpeculativeStreamingBrain(Brain())
    await cache.prepare(TurnContent(text="完整用户输入", generation=1))
    state = cache._state
    await state.task
    assert sum(len(text.encode()) for text in state.chunks) <= 64 * 1024


async def test_uncommitted_audio_cache_rejects_oversized_output_before_retaining_it():
    class Brain:
        async def stream(self, turn):
            yield "完整回复"

    class Tts:
        async def synthesize_duplex(self, texts):
            async for _ in texts:
                yield SynthesizedAudioChunk(pcm16=b"\0" * (16 * 1024 * 1024),
                                            sample_rate_hz=16000, is_final=False)

    cache = SpeculativeSpeechPipeline(brain=Brain(), tts=Tts())
    await cache.prepare(TurnContent(text="完整用户输入", generation=1))
    state = cache._state
    await state.task
    assert sum(len(chunk.pcm16) for chunk in state.audio_chunks) <= 8 * 1024 * 1024


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_replacement_never_starts_before_old_provider_really_exits(kind):
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            if turn.text == "旧":
                try:
                    entered.set()
                    yield "首包"
                finally:
                    closing.set()
                    await release.wait()
            yield "回复"

    cache = (SpeculativeStreamingBrain(Brain()) if kind == "text"
             else SpeculativeSpeechPipeline(brain=Brain(), tts=EchoTts()))
    await cache.prepare(TurnContent(text="旧", generation=1))
    original = cache._state.task
    await entered.wait()
    replacement = asyncio.create_task(cache.prepare(TurnContent(text="新", generation=2)))
    try:
        await asyncio.wait_for(closing.wait(), .5)
        await asyncio.sleep(.02)
        assert calls == ["旧"], "replacement admitted before actual cleanup"
    finally:
        release.set()
        await asyncio.gather(original, replacement, return_exceptions=True)
        await cache.invalidate(2, reason="test_cleanup")


from dataclasses import replace

from server.core.async_stream import OwnedStreamCleanupError
from server.realtime.capabilities.speculative_budget import (
    SpeculativeBudgetExceeded,
    SpeculativeOutputBudget,
)


def small_budget(**changes):
    return replace(SpeculativeOutputBudget(), text_bytes=24, text_chunks=3,
                   audio_bytes=128, audio_chunks=3, audio_seconds=1, **changes)


def make_cache(kind, brain, *, tts=None, budget=None, observer=None):
    if kind == "text":
        return SpeculativeStreamingBrain(brain, budget=budget, observer=observer)
    return SpeculativeSpeechPipeline(brain=brain, tts=tts or EchoTts(),
                                     budget=budget, observer=observer)


@pytest.mark.parametrize("kind", ["text", "speech"])
@pytest.mark.parametrize("overflow", ["bytes", "chunks"])
async def test_candidate_overflow_clears_cache_and_bypasses_without_truncating_input(kind, overflow):
    calls, closed, events = [], [], []
    turn = TurnContent(text="原始完整输入" * 100, generation=1)

    class Brain:
        async def stream(self, value):
            calls.append(value)
            try:
                if len(calls) == 1:
                    for text in (["中文中文", "中文中文", "多"] if overflow == "bytes" else ["a"] * 4):
                        yield text
                else:
                    assert closed == [1]
                    yield "正式回复"
            finally:
                closed.append(len(calls))

    cache = make_cache(kind, Brain(), budget=small_budget(),
                       observer=lambda op, _, attrs: events.append((op, attrs)))
    await cache.prepare(turn)
    state = cache._state
    await asyncio.wait_for(state.task, .5)
    assert isinstance(state.error, SpeculativeBudgetExceeded)
    assert not (state.chunks if kind == "text" else state.text_chunks)
    assert [text async for text in cache.stream(turn)] == ["正式回复"]
    assert calls == [turn, turn]
    assert ("miss", {"reason": "budget_bypass"}) in events
    if kind == "speech":
        async def texts():
            yield "正式回复"
        assert b"".join([chunk.pcm16 async for chunk in cache.synthesize_duplex(texts())]) == "正式回复".encode()


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_silent_candidate_residency_expires_and_retains_pending_supplier(kind):
    entered, exited, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Brain:
        async def stream(self, turn):
            try:
                entered.set()
                await release.wait()
                yield "late"
            finally:
                exited.set()

    cache = make_cache(kind, Brain(), budget=small_budget(candidate_seconds=.03))
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    try:
        await entered.wait()
        await asyncio.sleep(.04)
        assert not state.task.done() and not exited.is_set()
        assert isinstance(state.error, SpeculativeBudgetExceeded)
        assert str(state.error) == "candidate_residency"
        with pytest.raises(OwnedStreamCleanupError, match="pending"):
            await cache.prepare(TurnContent(text="新问题", generation=2))
        release.set()
        await asyncio.wait_for(state.task, .5)
        assert exited.is_set()
    finally:
        release.set()
        await asyncio.gather(state.task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_completed_candidate_also_expires_before_formal_claim(kind):
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn)
            yield "old" if len(calls) == 1 else "fresh"

    cache = make_cache(kind, Brain(), budget=small_budget(candidate_seconds=.02))
    turn = TurnContent(text="问题", generation=1)
    await cache.prepare(turn)
    await cache._state.task
    await asyncio.sleep(.025)
    assert [text async for text in cache.stream(turn)] == ["fresh"]
    assert calls == [turn, turn]
    if kind == "speech":
        async def texts():
            yield "fresh"
        assert [chunk async for chunk in cache.synthesize_duplex(texts())]
        await cache.invalidate(1, reason="test_cleanup")


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_committed_stream_drains_with_backpressure_and_never_restarts(kind):
    release, entered = asyncio.Event(), asyncio.Event()
    expected = [str(index % 10) * 2 for index in range(100)]
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn)
            entered.set()
            yield expected[0]
            await release.wait()
            for text in expected[1:]:
                yield text

    cache = make_cache(kind, Brain(), budget=small_budget(candidate_seconds=.03))
    turn = TurnContent(text="问题", generation=1)
    await cache.prepare(turn)
    state = cache._state
    await entered.wait()
    if kind == "text":
        output = cache.stream(turn)
        first = await anext(output)
        await asyncio.sleep(.04)  # Formal ownership has moved to the Core deadline.
        assert await cache.prepare(replace(turn, text="新问题")) is False
        release.set()
        actual = [first]
        async for text in output:
            assert state.chunks.bytes <= 24 and len(state.chunks) <= 3
            actual.append(text)
        assert actual == expected
    else:
        output = cache.synthesize_duplex(cache.stream(turn))
        first = await anext(output)
        await asyncio.sleep(.04)
        assert await cache.prepare(replace(turn, text="新问题")) is False
        release.set()
        actual = [first.pcm16]
        async for chunk in output:
            assert state.text_chunks.bytes <= 24 and len(state.text_chunks) <= 3
            assert state.audio_chunks.bytes <= 128 and len(state.audio_chunks) <= 3
            actual.append(chunk.pcm16)
        assert b"".join(actual) == "".join(expected).encode()
        assert not state.text_chunks and not state.audio_chunks
    assert len(calls) == 1
    assert state.done and state.error is None


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_cancelled_replacement_waiter_retains_actual_cleanup_owner(kind):
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            if turn.text == "旧":
                try:
                    entered.set()
                    yield "首包"
                finally:
                    closing.set()
                    await release.wait()
            yield "回复"

    cache = make_cache(kind, Brain())
    await cache.prepare(TurnContent(text="旧", generation=1))
    old = cache._state.task
    await entered.wait()
    replacement = asyncio.create_task(cache.prepare(TurnContent(text="新", generation=2)))
    try:
        await closing.wait()
        replacement.cancel()
        await asyncio.gather(replacement, return_exceptions=True)
        with pytest.raises(OwnedStreamCleanupError, match="remains pending"):
            await cache.prepare(TurnContent(text="再次", generation=3))
        assert calls == ["旧"] and not old.done()
        release.set()
        await asyncio.gather(old, return_exceptions=True)
        assert await cache.prepare(TurnContent(text="再次", generation=3))
        await cache.invalidate(3, reason="test_cleanup")
    finally:
        release.set()
        await asyncio.gather(old, replacement, return_exceptions=True)


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_failed_provider_cleanup_quarantines_every_new_admission(kind):
    entered = asyncio.Event()
    calls = []

    class Iterator:
        def __init__(self):
            self.sent = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return "ok"
        async def aclose(self):
            entered.set()
            raise RuntimeError("physical close failed")

    class Brain:
        def stream(self, turn):
            calls.append(turn)
            return Iterator()

    cache = make_cache(kind, Brain())
    turn = TurnContent(text="旧", generation=1)
    await cache.prepare(turn)
    await entered.wait()
    with pytest.raises(OwnedStreamCleanupError, match="physical close failed"):
        await cache.invalidate(1, reason="rewrite")
    with pytest.raises(OwnedStreamCleanupError, match="physical close failed"):
        await cache.prepare(replace(turn, text="新"))
    with pytest.raises(OwnedStreamCleanupError, match="physical close failed"):
        await anext(cache.stream(replace(turn, text="新")))
    assert calls == [turn]


async def test_tts_failure_wakes_brain_waiting_for_queue_or_provider_and_closes_it():
    exited = asyncio.Event()

    class Brain:
        async def stream(self, turn):
            try:
                for _ in range(100):
                    yield "first"
            finally:
                exited.set()

    class Tts:
        async def synthesize_duplex(self, texts):
            async for _ in texts:
                raise RuntimeError("ordinary TTS request failed")
                yield None

    cache = make_cache("speech", Brain(), tts=Tts())
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    await asyncio.wait_for(state.task, .5)
    assert exited.is_set()
    assert str(state.error) == "ordinary TTS request failed"
    assert state.cleanup_error is None


@pytest.mark.parametrize("field,value", [("text_bytes", 0), ("audio_chunks", -1),
                                         ("candidate_seconds", float("inf")), ("audio_seconds", 0)])
def test_invalid_budget_configuration_is_rejected(field, value):
    with pytest.raises(ValueError):
        replace(SpeculativeOutputBudget(), **{field: value})


async def test_direct_text_consumer_reserves_its_tts_lease_against_a_new_candidate():
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            yield turn.text

    tts = EchoTts()
    cache = make_cache("speech", Brain(), tts=tts)
    turn = TurnContent(text="原文", generation=1)
    text = [part async for part in cache.stream(turn)]
    assert await cache.prepare(TurnContent(text="新文", generation=2)) is False
    assert calls == ["原文"]
    async def texts():
        for part in text:
            yield part
    assert b"".join([chunk.pcm16 async for chunk in cache.synthesize_duplex(texts())]) == "原文".encode()
    assert await cache.prepare(TurnContent(text="新文", generation=2)) is True
    await cache.invalidate(2, reason="test_cleanup")


async def test_invalidation_during_budget_failure_cannot_cancel_real_tts_cleanup_twice():
    closing, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            yield "ok"
            yield "x" * 100

    class Tts:
        async def synthesize_duplex(self, texts):
            try:
                await anext(texts)
                yield SynthesizedAudioChunk(pcm16=b"00", sample_rate_hz=1000, is_final=False)
            finally:
                closing.set()
                await release.wait()
                closed.set()

    cache = make_cache("speech", Brain(), tts=Tts(), budget=small_budget())
    await cache.prepare(TurnContent(text="旧", generation=1))
    state = cache._state
    invalidation = None
    try:
        await asyncio.wait_for(closing.wait(), .5)
        invalidation = asyncio.create_task(cache.invalidate(1, reason="rewrite"))
        await asyncio.sleep(.02)
        assert not state.task.done() and not invalidation.done()
        with pytest.raises(OwnedStreamCleanupError, match="pending"):
            await cache.prepare(TurnContent(text="新", generation=2))
        assert calls == ["旧"] and not closed.is_set()
        release.set()
        await asyncio.gather(state.task, invalidation, return_exceptions=True)
        assert closed.is_set()
    finally:
        release.set()
        await asyncio.gather(state.task, *([invalidation] if invalidation else []), return_exceptions=True)


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_rejected_supplier_packet_is_not_retained_by_the_error_traceback(kind):
    class Brain:
        async def stream(self, turn):
            yield "x" * (256 * 1024)

    cache = make_cache(kind, Brain())
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    await state.task
    assert isinstance(state.error, SpeculativeBudgetExceeded)
    assert state.error.__traceback__ is None
    assert state.error.__cause__ is None and state.error.__context__ is None


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_completed_candidate_releases_payload_on_its_residency_deadline(kind):
    class Brain:
        async def stream(self, turn):
            yield "ok"

    cache = make_cache(kind, Brain(), budget=small_budget(candidate_seconds=.02))
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    await state.task
    await asyncio.sleep(.03)
    assert isinstance(state.error, SpeculativeBudgetExceeded)
    assert not (state.chunks if kind == "text" else state.text_chunks)
    if kind == "speech":
        assert not state.audio_chunks


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_direct_brain_cleanup_failure_is_sticky_for_prefetch_admission(kind):
    calls = []

    class Iterator:
        def __init__(self):
            self.sent = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return "ok"
        async def aclose(self):
            raise RuntimeError("direct socket cleanup failed")

    class Brain:
        def stream(self, turn):
            calls.append(turn)
            return Iterator()

    cache = make_cache(kind, Brain())
    turn = TurnContent(text="问题", generation=1)
    with pytest.raises(OwnedStreamCleanupError, match="direct socket cleanup failed"):
        assert [text async for text in cache.stream(turn)]
    with pytest.raises(OwnedStreamCleanupError, match="direct socket cleanup failed"):
        await cache.prepare(replace(turn, text="新问题"))
    assert calls == [turn]


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_retirement_cannot_cut_short_a_suppliers_natural_finally(kind):
    closing, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            if turn.text == "旧":
                try:
                    yield "ok"
                finally:
                    closing.set()
                    await release.wait()
                    closed.set()
            else:
                yield "new"

    cache = make_cache(kind, Brain())
    await cache.prepare(TurnContent(text="旧", generation=1))
    state = cache._state
    invalidation = None
    try:
        await closing.wait()
        invalidation = asyncio.create_task(cache.invalidate(1, reason="rewrite"))
        await asyncio.sleep(.02)
        assert not state.task.done() and not closed.is_set()
        with pytest.raises(OwnedStreamCleanupError, match="pending"):
            await cache.prepare(TurnContent(text="新", generation=2))
        assert calls == ["旧"]
        release.set()
        await asyncio.gather(state.task, invalidation, return_exceptions=True)
        assert closed.is_set()
        assert await cache.prepare(TurnContent(text="新", generation=2))
        await cache.invalidate(2, reason="test_cleanup")
    finally:
        release.set()
        await asyncio.gather(state.task, *([invalidation] if invalidation else []), return_exceptions=True)


@pytest.mark.parametrize("prepared", [False, True])
async def test_empty_reply_does_not_reserve_a_nonexistent_tts_consumer(prepared):
    class Brain:
        async def stream(self, turn):
            if turn.text == "empty":
                return
            yield turn.text

    cache = make_cache("speech", Brain())
    turn = TurnContent(text="empty", generation=1)
    if prepared:
        await cache.prepare(turn)
    assert [text async for text in cache.stream(turn)] == []
    assert [text async for text in cache.stream(TurnContent(text="new", generation=2))] == ["new"]
    async def texts():
        yield "new"
    assert [chunk async for chunk in cache.synthesize_duplex(texts())]


@pytest.mark.parametrize("mode", ["text", "pcm", "invalid_pcm_rate"])
async def test_rejected_large_packet_releases_actual_retained_memory(mode):
    import gc
    import tracemalloc

    class Brain:
        async def stream(self, turn):
            yield "x" * (8 * 1024 * 1024) if mode == "text" else "ok"

    class Tts:
        async def synthesize_duplex(self, texts):
            async for _ in texts:
                yield SynthesizedAudioChunk(pcm16=b"\0" * (16 * 1024 * 1024),
                                            sample_rate_hz=0 if mode == "invalid_pcm_rate" else 16000,
                                            is_final=False)

    # Measure cache retention after all provider locals/child tasks have ended,
    # excluding supplier-side peak allocation while constructing the packet.
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        cache = make_cache("text" if mode == "text" else "speech", Brain(), tts=Tts())
        await cache.prepare(TurnContent(text="问题", generation=1))
        state = cache._state
        await state.task
        await asyncio.sleep(0)
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - before
        assert retained < 1024 * 1024
        assert state.error is not None and state.error.__traceback__ is None
    finally:
        tracemalloc.stop()


async def test_finite_brain_close_does_not_block_end_marker_after_tts_failure():
    closed = asyncio.Event()

    class Brain:
        async def stream(self, turn):
            try:
                yield "one"
                yield "two"
            finally:
                closed.set()

    class Tts:
        async def synthesize_duplex(self, texts):
            await anext(texts)
            await closed.wait()
            raise RuntimeError("tts after text done")
            yield None

    cache = make_cache("speech", Brain(), tts=Tts())
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    await asyncio.wait_for(state.task, .5)
    assert state.done and str(state.error) == "tts after text done"
    assert state.cleanup_error is None


@pytest.mark.parametrize("dimension", ["bytes", "seconds", "metadata", "chunks"])
async def test_audio_cache_checks_each_budget_before_append(dimension):
    class Brain:
        async def stream(self, turn):
            yield "ok"

    class Tts:
        async def synthesize_duplex(self, texts):
            async for _ in texts:
                for _ in range(4 if dimension == "chunks" else 1):
                    yield SynthesizedAudioChunk(
                        pcm16=b"00" * (65 if dimension == "bytes" else 2),
                        sample_rate_hz=1 if dimension == "seconds" else 16000,
                        is_final=False,
                        sentence_text="x" * 25 if dimension == "metadata" else None)

    cache = make_cache("speech", Brain(), tts=Tts(), budget=small_budget())
    await cache.prepare(TurnContent(text="问题", generation=1))
    state = cache._state
    await state.task
    assert isinstance(state.error, SpeculativeBudgetExceeded)
    assert not state.audio_chunks and state.audio_chunks.bytes == 0


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_exact_budget_boundary_is_accepted(kind):
    class Brain:
        async def stream(self, turn):
            for text in ["中文", "中文", "中文中文"]:
                yield text

    cache = make_cache(kind, Brain(), budget=small_budget())
    turn = TurnContent(text="问题", generation=1)
    await cache.prepare(turn)
    state = cache._state
    await state.task
    assert state.error is None
    text = [delta async for delta in cache.stream(turn)]
    assert "".join(text) == "中文" * 4
    if kind == "speech":
        async def texts():
            for delta in text:
                yield delta
        assert b"".join([chunk.pcm16 async for chunk in cache.synthesize_duplex(texts())]) == ("中文" * 4).encode()


async def test_failed_retiring_candidate_cannot_be_promoted_to_formal_cancellation():
    closing, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Brain:
        async def stream(self, turn):
            try:
                yield "one"
            finally:
                closing.set()
                await release.wait()
                closed.set()

    class Tts:
        async def synthesize_duplex(self, texts):
            await anext(texts)
            await closing.wait()
            raise RuntimeError("TTS failed during natural Brain cleanup")
            yield None

    cache = make_cache("speech", Brain(), tts=Tts())
    turn = TurnContent(text="问题", generation=1)
    await cache.prepare(turn)
    state = cache._state
    consumer = None
    try:
        await closing.wait()
        async with asyncio.timeout(.5):
            while not state.retired.is_set():
                await asyncio.sleep(0)
        consumer = asyncio.create_task(anext(cache.stream(turn)))
        await asyncio.sleep(.01)
        assert not state.claimed, "failed retired candidate cannot become a cancellable formal lease"
        with pytest.raises(OwnedStreamCleanupError, match="pending"):
            await consumer
        assert not state.task.done() and not closed.is_set()
        release.set()
        await state.task
        assert closed.is_set()
    finally:
        release.set()
        await asyncio.gather(state.task, *([consumer] if consumer else []), return_exceptions=True)


@pytest.mark.parametrize("kind", ["text", "speech"])
@pytest.mark.parametrize("operation", ["prepare", "stream"])
async def test_closing_wins_admission_wait_without_starting_a_new_supplier(kind, operation):
    closing, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn.text)
            if turn.text == "old":
                try:
                    yield "one"
                finally:
                    closing.set()
                    await release.wait()
            else:
                yield "new"

    cache = make_cache(kind, Brain())
    await cache.prepare(TurnContent(text="old", generation=1))
    await closing.wait()
    turn = TurnContent(text="new", generation=2)

    async def admit():
        if operation == "prepare":
            return await cache.prepare(turn)
        return [text async for text in cache.stream(turn)]

    pending = asyncio.create_task(admit())
    shutdown = None
    try:
        # It owns the cache lock while waiting on the old real cleanup.
        async with asyncio.timeout(.5):
            while not cache._lock.locked():
                await asyncio.sleep(0)
        shutdown = asyncio.create_task(cache.close())
        async with asyncio.timeout(.5):
            while not cache._closed:
                await asyncio.sleep(0)
        release.set()
        await asyncio.gather(pending, shutdown, return_exceptions=True)
        assert calls == ["old"], "an admission await cannot cross the published close intent"
        with pytest.raises(RuntimeError, match="closed"):
            await pending
    finally:
        release.set()
        await asyncio.gather(pending, *([shutdown] if shutdown else []), return_exceptions=True)
