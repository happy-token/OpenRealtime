from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from server.realtime.capabilities.asr import AsrCommitRejected, AsrEndpointHint, AsrTranscriptDelta, AsrTranscriptFinal
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    AssistantYieldRequested,
    ObserveAsrEvent,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    ObserveVadEvent,
    SemanticInputRejected,
    UserTurnCommitted,
)
from server.realtime.capabilities.vad import VadSpeechStarted, VadSpeechStopped
from server.turn_policy.coordination import FloorOwner
from server.turn_policy.eot_classifier import EotClassification, EotDecision
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_interruption import InterruptionClassification, InterruptionLabel
from tests.realtime.test_cascaded_capabilities import context


class Endpoint:
    def __init__(self, decision=EotDecision.COMPLETE):
        self.decision = decision
        self.requests = []

    async def classify_request(self, request):
        self.requests.append(request)
        return EotClassification(self.decision)


class Interrupt:
    def __init__(self, label=InterruptionLabel.INTERRUPT):
        self.label = label

    async def classify_request(self, request):
        return InterruptionClassification(self.label, 1)


async def opened(**kwargs):
    kwargs.setdefault("semantic_interruption_classifier", Interrupt())
    return await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy,
        asr_idle_stop_ms=15,
        incomplete_timeout_ms=20,
        semantic_interruption_idle_ms=5,
        recovery_timeout_ms=100,
        **kwargs,
    ).open(context=context())


async def take(stream, kind):
    async with asyncio.timeout(0.5):
        async for event in stream:
            if isinstance(event, kind):
                return event
    raise AssertionError(f"missing {kind}")


async def text(session, value="查上海天气", revision=1, ctx=None):
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=ctx or context(),
                revision=revision,
                delta=value,
                accumulated_text=value,
                audio_timestamp_us=100,
            )
        )
    )


async def start(session, ctx=None):
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=ctx or context(),
                audio_timestamp_us=100,
            )
        )
    )


async def stop(session, ctx=None):
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=ctx or context(),
                audio_timestamp_us=200,
                silence_duration_us=100,
            )
        )
    )


@pytest.mark.asyncio
async def test_complete_input_commits_once_and_final_is_authoritative():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await session.send(
            ObserveAsrEvent(
                event=AsrTranscriptFinal(
                    context=context(),
                    revision=2,
                    text="查上海明天天气",
                    reason="final",
                )
            )
        )
        final = await take(stream, UserTurnCommitted)
        assert final.text == "查上海明天天气"
        await session.send(
            ObserveAsrEvent(
                event=AsrTranscriptFinal(
                    context=context(),
                    revision=2,
                    text=final.text,
                    reason="duplicate",
                )
            )
        )
        assert session.snapshot().input_id is None
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_restart_does_not_replace_input_or_commit_before_second_stop():
    session = await opened(eot_classifier=Endpoint(EotDecision.INCOMPLETE))
    stream = session.events()
    try:
        await start(session)
        await text(session, "从北京到")
        identity = session.snapshot().input_id
        await stop(session)
        await start(session)
        await text(session, "从北京到上海", 2)
        await asyncio.sleep(0.03)
        assert not session.snapshot().commit_pending
        assert session.snapshot().input_id == identity
        await stop(session)
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_vad_oscillation_does_not_restart_recovery_deadline():
    class NeverCompletePolicy:
        def endpoint_wait_ms(self, result):
            return 10000

        def interruption(self, verdict):
            raise AssertionError("no interruption")

    session = await opened(
        eot_classifier=Endpoint(EotDecision.INCOMPLETE),
        coordination_policy_factory=NeverCompletePolicy,
    )
    stream = session.events()
    try:
        await start(session)
        await text(session)
        for _ in range(5):
            await stop(session)
            await asyncio.sleep(0.01)
            await start(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_slow_model_does_not_block_resumption_and_stale_result_is_rejected():
    first = asyncio.Event()
    release = asyncio.Event()

    class Slow:
        async def classify_request(self, request):
            if request.text == "旧文字":
                first.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # provider ignores cancellation
                return EotClassification(EotDecision.COMPLETE)
            return EotClassification(EotDecision.INCOMPLETE)

    session = await opened(eot_classifier=Slow())
    try:
        await start(session)
        await text(session, "旧文字")
        await asyncio.wait_for(first.wait(), 0.2)
        await stop(session)
        await asyncio.wait_for(start(session), 0.05)
        await text(session, "新文字未完整", 2)
        release.set()
        await asyncio.sleep(0.02)
        assert session.snapshot().transcript_revision == 2
        assert not session.snapshot().commit_pending
    finally:
        release.set()
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("label", [InterruptionLabel.UNCERTAIN, InterruptionLabel.IGNORE])
async def test_model_negative_result_preserves_playback(label):
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt(label))
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session)
        await stop(session)
        await asyncio.sleep(0.03)
        assert session.snapshot().response_id == "a"
        assert session._input is None if label is InterruptionLabel.IGNORE else not session._input.yield_pending
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_stop_then_correction_keeps_collecting_and_uses_final_intent():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "别说了")
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id=session.snapshot().response_id)))
        await text(session, "别说了，查上海天气", 2)
        await stop(session)
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_question_answer_is_not_suppressed_by_backchannel_rule():
    session = await opened(
        eot_classifier=Endpoint(),
        semantic_interruption_classifier=Interrupt(InterruptionLabel.BACKCHANNEL),
    )
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await session.send(ObserveAssistantSpokenText(context=replace(context(), response_id="a"), text="是质量问题吗？"))
        await start(session)
        await text(session, "嗯")
        await stop(session)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id=session.snapshot().response_id)))
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_rule_backchannel_preserves_response():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "嗯嗯")
        await stop(session)
        await take(stream, AsrDiscardRequested)
        assert session.snapshot().response_id == "a"
        assert session.snapshot().floor is FloorOwner.ASSISTANT
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_old_completion_cannot_close_new_response():
    session = await opened()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await session.send(
            ObserveSystemResponseStarted(response_id="b", context=replace(context(), generation=2))
        )
        await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        assert session.snapshot().response_id == "b"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_missing_asr_final_has_explicit_failure_not_unbounded_wait():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await text(session)
        await take(stream, AsrCommitRequested)
        with pytest.raises(TimeoutError, match="asr_final"):
            await take(stream, UserTurnCommitted)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_provider_endpoint_without_vad_can_complete():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await session.send(
            ObserveAsrEvent(
                event=AsrEndpointHint(
                    context=context(),
                    revision=1,
                    text="你好",
                )
            )
        )
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "test_append_audio_reaches_one_committed_public_user_transcript",
        "test_projected_user_turn_streams_brain_text_into_tts_and_public_audio",
        "test_barge_in_stops_playback_even_after_response_generation_completed",
    ],
)
async def test_existing_engine_journal_audio_contracts_with_new_coordinator(monkeypatch, scenario):
    from tests.realtime import test_cascaded_engine as contracts

    monkeypatch.setattr(
        contracts, "LegacyTurnManagerCapabilityAdapter", CoordinatedTurnManagerCapabilityAdapter
    )
    await getattr(contracts, scenario)()


@pytest.mark.asyncio
async def test_continuous_interruptions_keep_new_input_and_response_identity():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        previous_id = None
        for generation in range(1, 4):
            ctx = replace(context(), generation=generation, turn_id=f"turn-{generation}")
            response = f"response-{generation}"
            await session.send(ObserveSystemResponseStarted(response_id=response, context=ctx))
            if previous_id:
                await session.send(ObserveSystemResponseCompleted(response_id=previous_id))
            await start(session, ctx)
            await text(session, f"改查第{generation}个城市", ctx=ctx)
            await stop(session, ctx)
            yielded = await take(stream, AssistantYieldRequested)
            assert yielded.context.response_id == response
            await session.send(ObserveAssistantYielded(context=replace(ctx, response_id=response)))
            await take(stream, AsrCommitRequested)
            await session.send(
                ObserveAsrEvent(
                    event=AsrTranscriptFinal(
                        context=ctx,
                        revision=1,
                        text=f"第{generation}个请求",
                        reason="final",
                    )
                )
            )
            final = await take(stream, UserTurnCommitted)
            assert final.context.turn_id == ctx.turn_id
            previous_id = response
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_model_failure_preserves_completed_input():
    class Broken:
        async def classify_request(self, request):
            raise TimeoutError("provider unavailable")

    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Broken())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session)
        await stop(session)
        await asyncio.sleep(0.03)
        assert session._input is not None and not session._input.yield_pending
        assert session.snapshot().response_id == "a"
        rejected = await take(stream, SemanticInputRejected)
        assert rejected.reason == "unresolved_overlap_deadline"
        assert session._input.rejected_text == "查上海天气"
        assert session.snapshot().response_id == "a"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_context_isolation_rejects_foreign_session_before_mutation():
    session = await opened()
    try:
        with pytest.raises(ValueError, match="another session"):
            await text(session, ctx=replace(context(), user_id="another-user"))
        assert session.snapshot().input_id is None
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_true_speech_with_stalled_asr_fails_explicitly_instead_of_fake_stop():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session)
        with pytest.raises(TimeoutError, match="ASR stalled"):
            await take(stream, AsrCommitRequested)
        assert not session.snapshot().commit_pending
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_semantic_backchannel_preserves_response():
    session = await opened(
        eot_classifier=Endpoint(),
        semantic_interruption_classifier=Interrupt(InterruptionLabel.BACKCHANNEL),
    )
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "嗯，我在听，你继续")
        await stop(session)
        await take(stream, AsrDiscardRequested)
        assert session.snapshot().response_id == "a"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_close_is_bounded_when_provider_ignores_cancel():
    entered, release = asyncio.Event(), asyncio.Event()

    class StubbornEndpoint:
        async def classify_request(self, request):
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            return EotClassification(EotDecision.COMPLETE)

    session = await opened(eot_classifier=StubbornEndpoint())
    try:
        await start(session)
        await text(session)
        await asyncio.wait_for(entered.wait(), 0.2)
        await asyncio.wait_for(session.close(), 0.3)
    finally:
        release.set()
        await session.close()
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_overlap_skips_endpoint_model_even_after_yield_and_text_revision():
    endpoint = Endpoint(EotDecision.INCOMPLETE)
    session = await opened(eot_classifier=endpoint, semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "改查上海")
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="a")))
        await text(session, "改查上海明天的天气", 2)
        assert not session.snapshot().commit_pending
        await stop(session)
        await take(stream, AsrCommitRequested)
        assert endpoint.requests == []
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_speech_start_during_finalization_survives_for_next_input():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await start(session)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=context(), revision=1, text="查上海天气", reason="final")))
        await take(stream, UserTurnCommitted)
        await text(session, "还有明天的", 2)
        await asyncio.sleep(0.025)
        assert not session.snapshot().commit_pending
        await admit_continuation_response(session, stream)
        await stop(session)
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_old_yield_ack_cannot_acknowledge_another_response_same_generation():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="b", context=context()))
        await start(session)
        await text(session)
        await stop(session)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="a")))
        assert not session.snapshot().commit_pending
        assert session.snapshot().response_id == "b"
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="b")))
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_replacement_response_becomes_target_of_pending_interruption():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session)
        await take(stream, AssistantYieldRequested)
        identity = session.snapshot().input_id
        await session.send(ObserveSystemResponseStarted(response_id="b", context=context()))
        request = await take(stream, AssistantYieldRequested)
        assert request.context.response_id == "b"
        assert session.snapshot().input_id == identity
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="a")))
        assert session.snapshot().response_id == "b"
        await stop(session)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="b")))
        await take(stream, AsrCommitRequested)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_new_transcript_during_finalization_is_not_lost_or_committed_twice():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await start(session)
        await text(session, "还有明天的", 2)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=context(), revision=1, text="查上海天气", reason="final")))
        await take(stream, UserTurnCommitted)
        assert session.snapshot().transcript_revision == 2
        assert not session.snapshot().commit_pending
        await admit_continuation_response(session, stream)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=context(), revision=2, text="还有明天的", reason="final")))
        result = await take(stream, UserTurnCommitted)
        assert result.text == "查上海天气\n还有明天的"
        assert session.snapshot().input_id is None
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_old_final_cannot_finish_deferred_turn_in_same_generation(rejected):
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    old = replace(context(), turn_id="old")
    new = replace(context(), turn_id="new")
    try:
        await start(session, old)
        await text(session, "旧请求", 3, old)
        await stop(session, old)
        await take(stream, AsrCommitRequested)
        await start(session, new)
        await text(session, "新请求", 1, new)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=old, revision=3, text="旧请求", reason="final")))
        await take(stream, UserTurnCommitted)
        assert session.snapshot().transcript_revision == 1
        await admit_continuation_response(session, stream, old, new)
        await stop(session, new)
        commit = await take(stream, AsrCommitRequested)
        assert commit.context.turn_id == "new"
        stale = AsrCommitRejected(context=old, reason="late") if rejected else AsrTranscriptFinal(
            context=old, revision=3, text="旧请求", reason="late")
        await session.send(ObserveAsrEvent(event=stale))
        assert session.snapshot().commit_pending
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=new, revision=1, text="新请求", reason="final")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "新请求"
        assert committed.input_relation == "unresolved"
        assert committed.related_turn_id == old.turn_id
        assert committed.context.turn_id == "new"
    finally:
        await stream.aclose()
        await session.close()

@pytest.mark.asyncio
async def test_before_first_audio_confirmed_continuation_merges_after_classification():
    endpoint = Endpoint()
    session = await opened(eot_classifier=endpoint, semantic_interruption_classifier=Interrupt())
    stream = session.events()
    first = context()
    next_context = replace(first, turn_id="next-turn", generation=first.generation + 1)
    try:
        await start(session, first)
        await text(session, "查天气", ctx=first)
        await stop(session, first)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="查天气", reason="final")))
        await take(stream, UserTurnCommitted)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=replace(first, response_id="a"), preparing=True))
        await start(session, next_context)
        await text(session, "还有明天", ctx=next_context)
        yielded = await take(stream, AssistantYieldRequested)
        assert yielded.context.response_id == "a"
        await session.send(ObserveAssistantYielded(context=replace(next_context, response_id="a")))
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=next_context, revision=1, text="还有明天", reason="final")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "查天气\n还有明天"
        assert committed.continuation_of_turn_id == first.turn_id
        assert len(endpoint.requests) == 1
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_playback_context_is_onset_prefix_and_stale_response_cannot_replace_it():
    class RecordingInterrupt(Interrupt):
        def __init__(self):
            super().__init__()
            self.requests = []
        async def classify_request(self, request):
            self.requests.append(request)
            return await super().classify_request(request)
    classifier = RecordingInterrupt()
    session = await opened(semantic_interruption_classifier=classifier)
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await session.send(ObserveAssistantSpokenText(context=replace(context(), response_id="a"), text="已听到第一句。"))
        await start(session)
        await session.send(ObserveAssistantSpokenText(context=replace(context(), response_id="old"), text="旧回复的全文"))
        await session.send(ObserveAssistantSpokenText(context=replace(context(), response_id="a"), text="已听到第一句。之后播放的第二句。"))
        await text(session, "我想换一个问题")
        await take(stream, AssistantYieldRequested)
        assert classifier.requests[-1].assistant_text == "已听到第一句。"
    finally:
        await session.close()


async def admit_continuation_response(session, stream, parent=None, current=None):
    await session.send(ObserveSystemResponseStarted(response_id="prepared", context=parent or context(), preparing=True))
    await take(stream, AssistantYieldRequested)
    await session.send(ObserveAssistantYielded(context=replace(current or context(), response_id="prepared")))

@pytest.mark.asyncio
async def test_deferred_continuation_does_not_call_eot_before_preparing_arrives():
    endpoint = Endpoint()
    session = await opened(eot_classifier=endpoint)
    stream = session.events()
    first = context()
    second = replace(first, turn_id="second", generation=first.generation + 1)
    try:
        await start(session, first)
        await text(session, "查天气", ctx=first)
        await stop(session, first)
        await take(stream, AsrCommitRequested)
        await start(session, second)
        await text(session, "还有明天", ctx=second)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="查天气", reason="final")))
        await take(stream, UserTurnCommitted)
        await asyncio.sleep(0.01)
        assert len(endpoint.requests) == 1
        await admit_continuation_response(session, stream, first, second)
        await stop(session, second)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=second, revision=1, text="还有明天", reason="final")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "查天气\n还有明天"
        assert committed.continuation_of_turn_id == first.turn_id
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_speech_after_playback_started_is_a_new_turn_not_continuation():
    session = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt())
    stream = session.events()
    first = context()
    second = replace(first, turn_id="second", generation=first.generation + 1)
    try:
        await start(session, first)
        await text(session, "查天气", ctx=first)
        await stop(session, first)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="查天气", reason="final")))
        await take(stream, UserTurnCommitted)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=first))
        # Start is a playback fact even when no complete sentence has been confirmed.
        await session.send(ObserveAssistantSpokenText(context=replace(first, response_id="a"), text=""))
        await start(session, second)
        await text(session, "换个问题查日期", ctx=second)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="a")))
        await stop(session, second)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=second, revision=1, text="换个问题查日期", reason="final")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "换个问题查日期"
        assert committed.continuation_of_turn_id is None
    finally:
        await session.close()

@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", ["停", "换个问题查日期"])
async def test_before_audio_stop_or_explicit_new_question_is_not_appended(utterance):
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    first = context()
    second = replace(first, turn_id="second", generation=first.generation + 1)
    try:
        await start(session, first)
        await text(session, "查天气", ctx=first)
        await stop(session, first)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="查天气", reason="final")))
        await take(stream, UserTurnCommitted)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=first, preparing=True))
        await start(session, second)
        await text(session, utterance, ctx=second)
        if utterance == "停":
            await stop(session, second)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="a")))
        if utterance != "停":
            await stop(session, second)
        if utterance == "停":
            await take(stream, AsrDiscardRequested)
            assert session.snapshot().input_id is None
        else:
            await take(stream, AsrCommitRequested)
            await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=second, revision=1, text=utterance, reason="final")))
            committed = await take(stream, UserTurnCommitted)
            assert committed.text == utterance
            assert committed.continuation_of_turn_id is None
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_semantic_stage_latency_covers_rule_path_without_model_calls():
    from unittest.mock import MagicMock
    from server.observability.telemetry import TelemetryOutcome
    telemetry = MagicMock()
    session = await opened(telemetry=telemetry)
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "别说了")
        await take(stream, AssistantYieldRequested)
        stage = [call for call in telemetry.record.call_args_list if call.args[0] == "semantic_interruption.classify"]
        assert stage
        assert stage[0].kwargs["duration_ms"] >= 0
        assert stage[0].kwargs["outcome"] == TelemetryOutcome.OK
        telemetry.provider_call.assert_not_called()
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_semantic_endpoint_stage_records_disabled_classifier_decision():
    from unittest.mock import MagicMock
    telemetry = MagicMock()
    session = await opened(telemetry=telemetry)
    stream = session.events()
    try:
        await text(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
        stages = [call for call in telemetry.record.call_args_list if call.args[0] == "turn_policy.eot_classify"]
        assert stages
        assert stages[0].kwargs["duration_ms"] >= 0
        telemetry.provider_call.assert_not_called()
    finally:
        await stream.aclose()
        await session.close()
