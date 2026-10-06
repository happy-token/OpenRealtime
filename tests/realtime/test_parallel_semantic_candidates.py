import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from server.realtime.capabilities.asr import AsrEndpointHint
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    AssistantYieldRequested,
    ObserveAsrEvent,
    ObserveSystemResponseStarted,
)
from server.turn_policy.eot_classifier import EotClassification, EotDecision
from server.turn_policy.semantic_interruption import InterruptionClassification, InterruptionLabel
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_chunk_coordination import opened
from tests.realtime.test_coordinated_turn_manager import start, stop, take, text

REPLAY = json.loads(
    (Path(__file__).parents[1] / "fixtures/voice-interaction/parallel-candidates.json").read_text()
)


async def wait_until(predicate):
    async with asyncio.timeout(0.5):
        while not predicate():
            await asyncio.sleep(0)


async def sentence_end(session, value, revision):
    await session.send(
        ObserveAsrEvent(event=AsrEndpointHint(context=context(), text=value, revision=revision))
    )


@pytest.mark.parametrize("equivalent_update", ["revision", "punctuation", "whitespace"])
async def test_equivalent_asr_update_keeps_original_endpoint_deadline(equivalent_update):
    requests = []

    class Endpoint:
        async def classify_request(self, request):
            requests.append(request)
            return EotClassification(EotDecision.INCOMPLETE, wait_ms=100)

    session = await opened(eot_classifier=Endpoint(), incomplete_timeout_ms=100)
    stream = session.events()
    try:
        await start(session)
        await sentence_end(session, "查北京天气。", 1)
        await wait_until(lambda: session._input.endpoint is not None)
        await stop(session)
        original_deadline = session._jobs["commit"]
        updated = {
            "revision": "查北京天气。",
            "punctuation": "查北京天气。！",
            "whitespace": " 查北京天气。 ",
        }[equivalent_update]
        await sentence_end(session, updated, 2)
        assert session._jobs["commit"] is original_deadline
        await take(stream, AsrCommitRequested)
        assert len(requests) == 1
    finally:
        await stream.aclose()
        await session.close()


async def test_commit_clears_completed_candidates_whose_results_are_still_queued():
    from server.realtime.capabilities.coordinated_turn_manager import _Result

    entered, release_old, release_latest, paused, resume = [asyncio.Event() for _ in range(5)]
    count = 0

    class Endpoint:
        async def classify_request(self, request):
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                await release_old.wait()
                return EotClassification(EotDecision.INCOMPLETE)
            await release_latest.wait()
            return EotClassification(EotDecision.COMPLETE)

    session = await opened(eot_classifier=Endpoint(), semantic_chunk_concurrency=2)
    original_handle = session._handle

    async def pause_result(event):
        if isinstance(event, _Result) and not paused.is_set():
            paused.set()
            await resume.wait()
        await original_handle(event)

    session._handle = pause_result
    stream = session.events()
    try:
        await start(session)
        await text(session, "查北京，", 1)
        await asyncio.wait_for(entered.wait(), 0.5)
        await text(session, "查北京，明天的天气。", 2)
        await stop(session)
        release_latest.set()
        await asyncio.wait_for(paused.wait(), 0.5)
        release_old.set()
        await wait_until(
            lambda: not any(key.startswith("endpoint_model:") for key in session._jobs)
        )
        assert len(session._tasks._requests) == 2
        resume.set()
        await take(stream, AsrCommitRequested)
        await wait_until(lambda: session._inbox.empty())
        assert session._tasks._requests == {}
    finally:
        release_old.set()
        release_latest.set()
        resume.set()
        await stream.aclose()
        await session.close()


async def test_unresolved_prefix_does_not_make_feedback_tail_discard_a_correction():
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            if len(requests) == 1:
                entered.set()
                await release.wait()
            return InterruptionClassification(InterruptionLabel.CORRECTION, 1)

    session = await opened(
        semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        await sentence_end(session, "改查上海天气，嗯。", 1)
        await asyncio.wait_for(entered.wait(), 0.5)
        await stop(session)
        release.set()
        event = await take(stream, AssistantYieldRequested)
        assert event.context.response_id == "old"
        assert [request.transcript for request in requests] == ["改查上海天气，", "嗯。"]
        assert requests[1].cumulative_transcript == "改查上海天气，嗯。"
    finally:
        release.set()
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize(
    ("confidence", "first_boundary", "confirmed_feedback"),
    [(0.9, "sentence_end", False), (0.99, "partial", False), (0.99, "sentence_end", True)],
)
async def test_tail_feedback_requires_prior_policy_confirmation(
    confidence, first_boundary, confirmed_feedback
):
    requests = []

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            return InterruptionClassification(
                InterruptionLabel.BACKCHANNEL
                if len(requests) == 1
                else InterruptionLabel.CORRECTION,
                confidence if len(requests) == 1 else 1,
            )

    session = await opened(semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        first_update = sentence_end if first_boundary == "sentence_end" else text
        await first_update(session, "天气改上海，", 1)
        await wait_until(
            lambda: session._input.verdict is not None and not session._input.chunks.busy
        )
        await sentence_end(session, "天气改上海，嗯。", 2)
        await stop(session)
        if confirmed_feedback:
            await take(stream, AsrDiscardRequested)
            assert len(requests) == 1  # Reliable prior feedback preserves the rule shortcut.
        else:
            event = await take(stream, AssistantYieldRequested)
            assert event.context.response_id == "old"
            assert len(requests) == 2
            assert requests[1].cumulative_transcript == "天气改上海，嗯。"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("latest_confidence", [0.7, 0.9, 0.99])
async def test_latest_partial_no_stop_is_separate_from_permission_to_discard(latest_confidence):
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            if len(requests) == 1:
                entered.set()
                await release.wait()
                return InterruptionClassification(InterruptionLabel.CORRECTION, 1)
            return InterruptionClassification(InterruptionLabel.BACKCHANNEL, latest_confidence)

    session = await opened(
        semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        await text(session, "天气改上海", 1)
        await asyncio.wait_for(entered.wait(), 0.5)
        await text(session, "天气改上海明天的天气", 2)
        expected_label = (
            InterruptionLabel.UNCERTAIN
            if latest_confidence == 0.7
            else InterruptionLabel.BACKCHANNEL
        )
        await wait_until(
            lambda: (
                session._input.verdict is not None
                and session._input.verdict.label is expected_label
            )
        )
        assert requests[1].cumulative_transcript == "天气改上海明天的天气"
        release.set()
        if expected_label is InterruptionLabel.UNCERTAIN:
            await take(stream, AssistantYieldRequested)
            assert session._input.floor_claim_confirmed
        else:
            await wait_until(lambda: not session._input.chunks.busy)
            assert not session._input.floor_claim_confirmed
            assert session._input.text == "天气改上海明天的天气"
            assert session._input.verdict.label is InterruptionLabel.BACKCHANNEL
            assert not any(
                isinstance(event, (AssistantYieldRequested, AsrDiscardRequested))
                for event in session._outbox._queue
            )
    finally:
        release.set()
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("operation", ["interrupt", "endpoint"])
async def test_rewrite_dispatches_new_candidate_after_cooperative_cancellation(operation):
    entered, cancelled, replacement_entered = [asyncio.Event() for _ in range(3)]
    requests = []

    class Classifier:
        async def classify_request(self, request):
            requests.append(request)
            if len(requests) == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            replacement_entered.set()
            return (
                InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
                if operation == "interrupt"
                else EotClassification(EotDecision.COMPLETE)
            )

    option = "semantic_interruption_classifier" if operation == "interrupt" else "eot_classifier"
    session = await opened(semantic_chunk_concurrency=1, **{option: Classifier()})
    try:
        if operation == "interrupt":
            await session.send(
                ObserveSystemResponseStarted(
                    response_id="old", context=replace(context(), response_id="old")
                )
            )
        await start(session)
        old, new = REPLAY["rewrite"][operation]
        send_text = text if operation == "interrupt" else sentence_end
        await send_text(session, old, 1)
        await asyncio.wait_for(entered.wait(), 0.5)
        await send_text(session, new, 2)
        await asyncio.wait_for(replacement_entered.wait(), 0.5)
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert len(requests) == REPLAY["rewrite"]["expected_dispatches"]
    finally:
        await session.close()


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_endpoint_semantics_are_cumulative_at_every_concurrency(concurrency):
    calls = []

    class Endpoint:
        async def classify_request(self, request):
            calls.append(request)
            return EotClassification(EotDecision.INCOMPLETE)

    session = await opened(eot_classifier=Endpoint(), semantic_chunk_concurrency=concurrency)
    try:
        await start(session)
        await text(session, *REPLAY["endpoint"]["asr_updates"][0])
        await wait_until(lambda: len(calls) == 1 and not session._input.chunks.busy)
        await text(session, *REPLAY["endpoint"]["asr_updates"][1])
        await wait_until(lambda: len(calls) == 2)
        assert [call.text for call in calls] == REPLAY["endpoint"]["expected_cumulative"]
        assert calls[1].input_state.previous_chunks == ("查北京，",)
    finally:
        await session.close()


@pytest.mark.parametrize(
    "old_label", [InterruptionLabel.STOP, InterruptionLabel.CORRECTION, InterruptionLabel.INTERRUPT]
)
@pytest.mark.parametrize("latest_label", [InterruptionLabel.IGNORE, InterruptionLabel.BACKCHANNEL])
@pytest.mark.parametrize("equivalent_update", [None, "revision", "punctuation"])
@pytest.mark.parametrize("scenario", REPLAY["negative_supersedes"], ids=lambda case: case["id"])
async def test_latest_full_ignore_supersedes_late_stopping_prefix_before_stop(
    old_label, latest_label, equivalent_update, scenario
):
    entered, release, latest = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Interrupt:
        async def classify_request(self, request):
            calls.append(request)
            if len(calls) == 1:
                entered.set()
                await release.wait()
                return InterruptionClassification(old_label, 1)
            latest.set()
            return InterruptionClassification(latest_label, 1)

    session = await opened(
        semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2
    )
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        await text(session, *scenario["asr_updates"][0])
        await asyncio.wait_for(entered.wait(), 0.5)
        for update in scenario["asr_updates"][1:]:
            await text(session, *update)
        await asyncio.wait_for(latest.wait(), 0.5)
        await wait_until(
            lambda: (
                session._input.verdict is not None and session._input.verdict.label is latest_label
            )
        )
        assert calls[1].cumulative_transcript == scenario["asr_updates"][-1][0]
        if equivalent_update is not None:
            value, revision = scenario["asr_updates"][-1]
            await text(
                session, value + ("。" if equivalent_update == "punctuation" else ""), revision + 1
            )
        release.set()
        await wait_until(lambda: not session._input.chunks.busy)
        assert session._input.verdict.label is latest_label
        assert len(calls) == 2
        assert not session._input.floor_claim_confirmed
        assert not session._input.yield_pending
        assert not any(
            isinstance(event, AssistantYieldRequested) for event in list(session._outbox._queue)
        )
    finally:
        release.set()
        await session.close()


async def test_latest_complete_commits_without_waiting_for_old_incomplete():
    first_entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Endpoint:
        async def classify_request(self, request):
            calls.append(request.text)
            if len(calls) == 1:
                first_entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                return EotClassification(EotDecision.INCOMPLETE)
            return EotClassification(EotDecision.COMPLETE)

    session = await opened(eot_classifier=Endpoint(), semantic_chunk_concurrency=2)
    stream = session.events()
    try:
        await start(session)
        await text(session, "查北京，", 1)
        await first_entered.wait()
        await text(session, "查北京，明天的天气。", 2)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert len(calls) == 2
        assert calls[1] == "查北京，明天的天气。"
    finally:
        release.set()
        await stream.aclose()
        await session.close()


async def test_late_complete_prefix_does_not_override_latest_incomplete():
    first_entered, release, second_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    count = 0

    class Endpoint:
        async def classify_request(self, request):
            nonlocal count
            count += 1
            if count == 1:
                first_entered.set()
                await release.wait()
                return EotClassification(EotDecision.COMPLETE)
            second_done.set()
            return EotClassification(EotDecision.INCOMPLETE)

    session = await opened(
        eot_classifier=Endpoint(), semantic_chunk_concurrency=2, incomplete_timeout_ms=10000
    )
    try:
        await start(session)
        await text(session, "查北京，", 1)
        await first_entered.wait()
        await text(session, "查北京，但是，", 2)
        await asyncio.wait_for(second_done.wait(), 0.5)
        await stop(session)
        release.set()
        await asyncio.sleep(0.02)
        assert session._input.endpoint.decision is EotDecision.INCOMPLETE
        assert not session._input.commit_pending
    finally:
        release.set()
        await session.close()


async def test_confirmed_parallel_interrupt_locks_and_cancels_other_candidate():
    first_entered, second_entered, release, cancelled = [asyncio.Event() for _ in range(4)]
    count = 0

    class Interrupt:
        async def classify_request(self, request):
            nonlocal count
            count += 1
            if count == 1:
                first_entered.set()
                await second_entered.wait()
                return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
            second_entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return InterruptionClassification(InterruptionLabel.IGNORE, 1)

    session = await opened(
        semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        await text(session, "改查上海的", 1)
        await first_entered.wait()
        await text(session, "改查上海的明天天气啊", 2)
        event = await take(stream, AssistantYieldRequested)
        assert event.context.response_id == "old"
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert session._input.floor_claim_confirmed
    finally:
        release.set()
        await stream.aclose()
        await session.close()


async def test_late_non_stopping_prefix_unblocks_latest_ignore_without_overwriting_it():
    from server.realtime.capabilities.turn_manager import AsrDiscardRequested

    entered, release, latest = asyncio.Event(), asyncio.Event(), asyncio.Event()
    count = 0

    class Interrupt:
        async def classify_request(self, request):
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                await release.wait()
                return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1)
            latest.set()
            return InterruptionClassification(InterruptionLabel.IGNORE, 1)

    session = await opened(
        semantic_interruption_classifier=Interrupt(), semantic_chunk_concurrency=2
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="old", context=replace(context(), response_id="old")
            )
        )
        await start(session)
        await text(session, "外面的声音", 1)
        await entered.wait()
        await text(session, "外面的声音来自电视机", 2)
        await asyncio.wait_for(latest.wait(), 0.5)
        await stop(session)
        release.set()
        await take(stream, AsrDiscardRequested)
        assert session._input is None
    finally:
        release.set()
        await stream.aclose()
        await session.close()
