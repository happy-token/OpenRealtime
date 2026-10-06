"""Actual JEV adapter admission and cancellation, with a controlled SDK transport."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from server.turn_policy.plugins.jev_classifier import (
    EOT_CRITERIA,
    JevClient,
    JevEotClassifier,
    JevSemanticInterruptionClassifier,
)
from server.turn_policy.semantic_interruption import InterruptionBoundary, InterruptionLabel


class ControlledSdk:
    def __init__(self, monkeypatch):
        self.created = 0
        self.active = 0
        self.peak = 0
        self.started = []
        self.entered = asyncio.Queue()
        self.releases = {}
        self.closed = 0
        self.ready = None
        self.preparing = asyncio.Event()
        owner = self

        class Client:
            def __init__(self, **kwargs):
                owner.created += 1

            async def __aenter__(self):
                owner.preparing.set()
                if owner.ready is not None:
                    await owner.ready.wait()
                return self

            async def __aexit__(self, *args):
                owner.closed += 1

            async def system_one(self, *, state, questions):
                text = state["transcript"]
                owner.started.append(text)
                owner.active += 1
                owner.peak = max(owner.peak, owner.active)
                release = owner.releases.setdefault(text, asyncio.Event())
                owner.entered.put_nowait(text)
                try:
                    await release.wait()
                    criteria = questions["decision"]["criteria"]
                    label = next(iter(criteria))
                    return SimpleNamespace(
                        model="jev-controlled",
                        choices={
                            "decision": SimpleNamespace(
                                choice=label,
                                confidence=1.0,
                                probabilities={key: float(key == label) for key in criteria},
                            )
                        },
                    )
                finally:
                    owner.active -= 1

        monkeypatch.setitem(
            sys.modules,
            "typesafe_sdk",
            SimpleNamespace(
                AsyncTypeSafeClient=Client,
                Choice=lambda **kwargs: kwargs,
                RetryPolicy=lambda **kwargs: kwargs,
            ),
        )

    async def next(self):
        return await asyncio.wait_for(self.entered.get(), 0.5)


def observe_waiting_slot(client, monkeypatch):
    waiting = asyncio.Queue()
    acquire = client._slots.acquire

    async def observed_acquire():
        if client._slots.locked():
            waiting.put_nowait(asyncio.current_task().get_name())
        return await acquire()

    monkeypatch.setattr(client._slots, "acquire", observed_acquire)
    return waiting


def choose(client, text):
    return client.choose(state={"transcript": text}, instructions="test", criteria=EOT_CRITERIA)


@pytest.mark.parametrize("reuse_connections", [False, True])
async def test_close_during_shared_slot_wait_never_opens_another_request(
    monkeypatch, reuse_connections
):
    sdk = ControlledSdk(monkeypatch)
    client = JevClient(api_key="test", max_concurrency=1, reuse_connections=reuse_connections)
    waiting = observe_waiting_slot(client, monkeypatch)
    active = asyncio.create_task(choose(client, "A"), name="A")
    queued = None
    try:
        assert await sdk.next() == "A"
        queued = asyncio.create_task(choose(client, "B"), name="B")
        assert await asyncio.wait_for(waiting.get(), 0.5) == "B"
        await client.close()
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
        with pytest.raises(RuntimeError, match="closed"):
            await asyncio.wait_for(queued, 0.5)
        assert sdk.started == ["A"]
        assert sdk.created == 1
        assert not client._slots.locked()
    finally:
        for task in (active, queued):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (active, queued) if task is not None), return_exceptions=True
        )
        await client.close()


@pytest.mark.parametrize("reuse_connections", [False, True])
async def test_close_during_client_preparation_never_starts_request(monkeypatch, reuse_connections):
    sdk = ControlledSdk(monkeypatch)
    sdk.ready = asyncio.Event()
    client = JevClient(api_key="test", max_concurrency=1, reuse_connections=reuse_connections)
    preparing = asyncio.create_task(choose(client, "A"))
    closing = None
    try:
        await asyncio.wait_for(sdk.preparing.wait(), 0.5)
        closing = asyncio.create_task(client.close())
        # Shared connection preparation owns the lock; closure must revoke
        # admission immediately, before waiting for that preparation to finish.
        await asyncio.sleep(0)
        sdk.ready.set()
        await asyncio.wait_for(closing, 0.5)
        with pytest.raises(RuntimeError, match="closed"):
            await asyncio.wait_for(preparing, 0.5)
        assert sdk.started == []
        assert sdk.closed == 1
        assert not client._slots.locked()
    finally:
        sdk.ready.set()
        preparing.cancel()
        await asyncio.gather(preparing, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await client.close()


@pytest.mark.parametrize("cancel_first_waiter", [False, True])
async def test_shared_capacity_keeps_wait_order_and_skips_cancelled_waiters(
    monkeypatch, cancel_first_waiter
):
    sdk = ControlledSdk(monkeypatch)
    client = JevClient(api_key="test", max_concurrency=2, reuse_connections=True)
    waiting = observe_waiting_slot(client, monkeypatch)
    endpoint = JevEotClassifier(client)
    interruption = JevSemanticInterruptionClassifier(client)
    tasks = {}

    async def request(name):
        if name.startswith("A"):
            return await endpoint.classify(text=name, generation=1)
        return await interruption.classify(
            assistant_text="正在回答",
            transcript=name,
            boundary=InterruptionBoundary.SENTENCE_END,
            generation=2,
        )

    try:
        for name in ("A1", "A2"):
            tasks[name] = asyncio.create_task(request(name), name=name)
            assert await sdk.next() == name
        for name in ("B1", "A3", "B2"):
            tasks[name] = asyncio.create_task(request(name), name=name)
            assert await asyncio.wait_for(waiting.get(), 0.5) == name
        if cancel_first_waiter:
            tasks["B1"].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks["B1"]
        sdk.releases["A1"].set()
        assert (await tasks["A1"]).decision.value == "complete"
        next_name = "A3" if cancel_first_waiter else "B1"
        assert await sdk.next() == next_name
        sdk.releases["A2"].set()
        await tasks["A2"]
        assert await sdk.next() == ("B2" if cancel_first_waiter else "A3")
        if not cancel_first_waiter:
            sdk.releases["B1"].set()
            assert (await tasks["B1"]).label is InterruptionLabel.BACKCHANNEL
            assert await sdk.next() == "B2"
        sdk.releases["A3"].set()
        sdk.releases["B2"].set()
        assert (await tasks["A3"]).decision.value == "complete"
        assert (await tasks["B2"]).label is InterruptionLabel.BACKCHANNEL
        assert sdk.peak == 2 and sdk.active == 0
        assert sdk.started == (
            ["A1", "A2", "A3", "B2"] if cancel_first_waiter else ["A1", "A2", "B1", "A3", "B2"]
        )
        assert sdk.created == 1
        assert not client._slots.locked()
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        await client.close()


async def test_closing_one_actor_releases_shared_slot_for_another_session(monkeypatch):
    from dataclasses import replace

    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        ObserveAsrEvent,
        UserTurnCommitted,
    )
    from server.turn_policy.policy import TurnPolicy
    from tests.realtime.test_coordinated_turn_manager import context, start, stop, take, text

    sdk = ControlledSdk(monkeypatch)
    client = JevClient(api_key="test", max_concurrency=1, reuse_connections=True)
    waiting = observe_waiting_slot(client, monkeypatch)
    sessions, streams = [], []
    try:
        for identity in ("A", "B"):
            ctx = replace(context(), voice_session_id=identity, thread_id=f"thread-{identity}")
            session = await CoordinatedTurnManagerCapabilityAdapter(
                TurnPolicy,
                eot_classifier=JevEotClassifier(client),
                asr_idle_stop_ms=5,
                classifier_timeout_ms=1500,
                recovery_timeout_ms=2000,
            ).open(context=ctx)
            sessions.append(session)
            streams.append(session.events())
            await start(session, ctx=ctx)
            await text(session, f"查询{identity}城市天气", ctx=ctx)
            await stop(session, ctx=ctx)
            if identity == "A":
                assert await sdk.next() == "查询A城市天气"
            else:
                await asyncio.wait_for(waiting.get(), 0.5)
        await sessions[0].close()
        assert await sdk.next() == "查询B城市天气"
        sdk.releases["查询B城市天气"].set()
        commit = await take(streams[1], AsrCommitRequested)
        assert commit.context.voice_session_id == "B"
        await sessions[1].send(
            ObserveAsrEvent(
                event=AsrTranscriptFinal(
                    context=commit.context, revision=2, text="查询B城市天气", reason="final"
                )
            )
        )
        final = await take(streams[1], UserTurnCommitted)
        assert final.context.voice_session_id == "B" and final.context.thread_id == "thread-B"
        assert final.text == "查询B城市天气"
        assert sdk.peak == 1 and sdk.active == 0
        assert not client._slots.locked()
    finally:
        for stream in streams:
            await stream.aclose()
        for session in sessions:
            await session.close()
        await client.close()
