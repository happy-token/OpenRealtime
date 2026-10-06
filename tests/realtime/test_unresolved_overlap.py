"""Replay the lost follow-up in session 95a9b382 (2026-10-06)."""

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from server.observability.telemetry import RuntimeDebugLog, SessionDebugLog
from server.realtime.capabilities.asr import AsrTranscriptFinal
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    ObserveAsrEvent,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    UserTurnCommitted,
)
from server.turn_policy.semantic_interruption import (
    InterruptionClassification,
    InterruptionLabel,
)
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_chunk_coordination import opened
from tests.realtime.test_coordinated_turn_manager import start, stop, take, text
from tests.realtime.test_parallel_semantic_candidates import sentence_end, wait_until


@pytest.mark.parametrize("finish_before_result", [False, True])
@pytest.mark.parametrize("latest_first", [False, True])
@pytest.mark.parametrize("raw_label", [InterruptionLabel.UNCERTAIN, InterruptionLabel.INTERRUPT])
async def test_uncertain_follow_up_is_not_lost_when_old_playback_finishes(
    finish_before_result, latest_first, raw_label
):
    requests = []
    release = [asyncio.Event(), asyncio.Event()]

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            index = len(requests) - 1
            await release[index].wait()
            return InterruptionClassification(raw_label, 0.5 if index == 0 else 0.26)

    session = await opened(semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2)
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="beijing-today", context=replace(context(), response_id="beijing-today")
            )
        )
        await start(session)
        await text(session, "明天天气", 14)
        await stop(session)
        await wait_until(lambda: len(requests) == 1)
        await sentence_end(session, "明天天气怎么样？", 16)
        await wait_until(lambda: len(requests) == 2)
        if finish_before_result:
            await session.send(ObserveSystemResponseCompleted(response_id="beijing-today"))
        for index in ([1, 0] if latest_first else [0, 1]):
            release[index].set()
            await wait_until(lambda index=index: not session._input.chunks.matches_active(requests[index].input_state.chunk_id))
        await wait_until(lambda: session._input.verdict is not None and not session._input.chunks.busy)
        assert not session._input.yield_pending  # UNCERTAIN alone must not stop playback.
        assert not session._input.floor_claim_confirmed
        if not finish_before_result:
            await session.send(ObserveSystemResponseCompleted(response_id="beijing-today"))
        committed = await take(stream, AsrCommitRequested)
        assert committed.context.turn_id == context().turn_id
        assert committed.reason == "deferred_overlap_after_playback"
        assert [r.cumulative_transcript for r in requests] == ["明天天气", "明天天气怎么样？"]
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=committed.context, text="明天天气怎么样？", revision=16, reason=committed.reason,
        )))
        turn = await take(stream, UserTurnCommitted)
        assert turn.text == "明天天气怎么样？"
        assert not session._tasks._requests
    finally:
        for signal in release:
            signal.set()
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("label", [InterruptionLabel.IGNORE, InterruptionLabel.BACKCHANNEL])
async def test_late_negative_verdict_after_natural_completion_is_still_applied(label):
    entered, release = asyncio.Event(), asyncio.Event()

    class Interrupt:
        async def classify_request(self, request):
            entered.set()
            await release.wait()
            return InterruptionClassification(label, 0.99)

    session = await opened(semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="old", context=context()))
        await start(session)
        await text(session, "无关内容。")
        await stop(session)
        await entered.wait()
        await session.send(ObserveSystemResponseCompleted(response_id="old"))
        release.set()
        discarded = await take(stream, AsrDiscardRequested)
        assert discarded.reason == "semantic_control_or_feedback"
        assert session._input is None
        assert not session._tasks._requests
    finally:
        release.set()
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("prefix_label", [InterruptionLabel.STOP, InterruptionLabel.CORRECTION, InterruptionLabel.INTERRUPT])
@pytest.mark.parametrize("finish_before_latest", [False, True])
async def test_expired_stopping_prefix_cannot_erase_follow_up_after_natural_completion(
    prefix_label, finish_before_latest
):
    requests = []
    release = [asyncio.Event(), asyncio.Event()]

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            index = len(requests) - 1
            await release[index].wait()
            return InterruptionClassification(prefix_label, 1) if index == 0 else InterruptionClassification(InterruptionLabel.UNCERTAIN, 0.5)

    session = await opened(semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2)
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="old", context=context()))
        await start(session)
        await text(session, "暂停一会儿，", 1)
        await wait_until(lambda: len(requests) == 1)
        await sentence_end(session, "暂停一会儿，明天天气怎么样？", 2)
        await stop(session)
        await wait_until(lambda: len(requests) == 2)
        if finish_before_latest:
            await session.send(ObserveSystemResponseCompleted(response_id="old"))
        release[1].set()
        await wait_until(lambda: session._input.verdict is not None)
        if not finish_before_latest:
            await session.send(ObserveSystemResponseCompleted(response_id="old"))
        assert not session._input.commit_pending
        release[0].set()
        committed = await take(stream, AsrCommitRequested)
        assert committed.reason == "deferred_overlap_after_playback"
        assert not session._input.floor_claim_confirmed
        assert session._input.verdict.label is InterruptionLabel.UNCERTAIN
        assert session._input.verdict.candidate.text == "暂停一会儿，明天天气怎么样？"
    finally:
        for signal in release:
            signal.set()
        await stream.aclose()
        await session.close()


async def test_debug_log_distinguishes_raw_model_label_from_confidence_downgrade():
    entries = []

    class Sink:
        def _enqueue(self, entry):
            entries.append(entry)

    class Interrupt:
        async def classify_request(self, request):
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 0.26)

    session = await opened(
        debug_log=SessionDebugLog(cast(RuntimeDebugLog, Sink()), "diagnosis"),
        semantic_interruption_classifier=Interrupt(),
    )
    try:
        await session.send(ObserveSystemResponseStarted(response_id="old", context=context()))
        await start(session)
        await text(session, "明天天气怎么样？")
        await stop(session)
        await wait_until(lambda: session._input.verdict is not None)
        decision = next(e for e in entries if e.stage == "interruption" and e.event == "decision")
        detail = decision.detail
        assert decision.summary == "label=uncertain source=model"
        assert detail["raw_label"] == "interrupt"
        assert detail["confidence_threshold"] == 0.8
        assert detail["below_confidence_threshold"] is True
        assert detail["should_stop"] is False
    finally:
        await session.close()
