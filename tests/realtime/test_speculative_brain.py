from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain


class EmptyOnceBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        del turn
        self.calls += 1
        if self.calls == 1:
            return
        yield "重试后的有效回复"


@pytest.mark.asyncio
async def test_empty_speculative_response_retries_at_commit_boundary() -> None:
    provider = EmptyOnceBrain()
    brain = SpeculativeStreamingBrain(provider)
    turn = TurnContent(text="你好", generation=1)

    assert await brain.prepare(turn) is True

    assert [delta async for delta in brain.stream(turn)] == ["重试后的有效回复"]
    assert provider.calls == 2


async def test_uncooperative_producer_does_not_block_invalidation():
    import asyncio

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Brain:
        async def stream(self, turn):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            yield "迟到的旧回复"

    brain = SpeculativeStreamingBrain(Brain())
    await brain.prepare(TurnContent(text="旧问题", generation=1))
    producer = brain._state.task
    try:
        await entered.wait()
        await asyncio.wait_for(brain.invalidate(1, reason="rewrite"), 0.3)
        assert cancelled.is_set()
        assert brain._state is None
    finally:
        release.set()
        await producer


async def test_hit_observation_and_context_mismatch_start_only_correct_response():
    from dataclasses import replace

    events = []

    class Brain:
        def __init__(self):
            self.turns = []

        async def stream(self, turn):
            self.turns.append(turn)
            yield turn.model_text

    provider = Brain()
    brain = SpeculativeStreamingBrain(
        provider,
        observer=lambda operation, turn, attributes: events.append((operation, attributes)),
    )
    original = TurnContent(text="你好。", generation=1, conversation_context="旧上下文")
    await brain.prepare(original)
    assert [delta async for delta in brain.stream(replace(original, text="你好！"))] == [
        original.model_text
    ]
    assert events[-1][0] == "hit"
    await brain.prepare(original)
    revised = replace(original, conversation_context="新上下文")
    assert [delta async for delta in brain.stream(revised)] == [revised.model_text]
    assert events[-1] == ("miss", {"reason": "candidate_mismatch"})


async def test_invalidation_wakes_consumer_without_restarting_old_reply():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Brain:
        async def stream(self, turn):
            calls.append(turn)
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            yield "过期回复"

    brain = SpeculativeStreamingBrain(Brain())
    turn = TurnContent(text="旧问题", generation=1)
    await brain.prepare(turn)
    producer = brain._state.task

    async def consume():
        return [delta async for delta in brain.stream(turn)]

    follower = asyncio.create_task(consume())
    try:
        await entered.wait()
        await asyncio.sleep(0)
        await brain.invalidate(1, reason="new_input")
        assert await asyncio.wait_for(follower, 0.2) == []
        assert len(calls) == 1
    finally:
        release.set()
        await producer
        if not follower.done():
            follower.cancel()
        await asyncio.gather(follower, return_exceptions=True)
