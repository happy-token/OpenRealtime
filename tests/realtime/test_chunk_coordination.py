import asyncio
from dataclasses import replace

from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.turn_manager import (
    AssistantYieldRequested,
    ObserveSystemResponseStarted,
)
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_interruption import InterruptionClassification, InterruptionLabel
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_coordinated_turn_manager import Endpoint, start, take, text


async def opened(**kwargs):
    return await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy,
        semantic_chunks_enabled=True,
        interruption_chunk_chars=5,
        chunk_stability_ms=5,
        recovery_timeout_ms=1000,
        **kwargs,
    ).open(context=context())


async def test_small_partial_updates_do_not_request_endpoint_until_boundary():
    endpoint = Endpoint()
    session = await opened(eot_classifier=endpoint)
    try:
        await start(session)
        for revision, phrase in enumerate(["查", "查上海", "查上海天气"], 1):
            await text(session, phrase, revision)
        await asyncio.sleep(0.01)
        assert endpoint.requests == []
        await text(session, "查上海天气。", 4)
        await asyncio.sleep(0.03)
        assert [request.text for request in endpoint.requests] == ["查上海天气。"]
    finally:
        await session.close()


async def test_new_partial_does_not_cancel_inflight_interruption_and_never_calls_eot():
    entered, release = asyncio.Event(), asyncio.Event()
    requests, cancellations = [], []

    class SlowInterrupt:
        async def classify_request(self, request):
            requests.append(request)
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellations.append(request)
                raise
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)

    endpoint = Endpoint()
    session = await opened(
        eot_classifier=endpoint, semantic_interruption_classifier=SlowInterrupt()
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "改查上海的", 1)
        await asyncio.wait_for(entered.wait(), 0.2)
        await text(session, "改查上海的明天天气", 2)
        await asyncio.sleep(0.01)
        assert len(requests) == 1
        assert cancellations == []
        release.set()
        event = await take(stream, AssistantYieldRequested)
        assert event.context.response_id == "a"
        assert endpoint.requests == []
    finally:
        release.set()
        await stream.aclose()
        await session.close()


async def test_chunk_five_char_trigger_bypasses_legacy_twenty_four_char_debounce():
    requests = []

    class Interrupt:
        async def classify_request(self, request):
            requests.append(request)
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)

    session = await opened(
        semantic_interruption_classifier=Interrupt(),
        semantic_interruption_partial_chars=24,
        semantic_interruption_idle_ms=1000,
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "改查上海的", 1)
        await take(stream, AssistantYieldRequested)
        assert len(requests) == 1
        assert requests[0].input_state.chunk_id
    finally:
        await stream.aclose()
        await session.close()


async def test_new_text_after_stop_ack_can_commit_without_endpoint():
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        ObserveAssistantYielded,
    )
    from tests.realtime.test_coordinated_turn_manager import Interrupt, stop

    endpoint = Endpoint()
    session = await opened(semantic_interruption_classifier=Interrupt(), eot_classifier=endpoint)
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "改查上海的", 1)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(context(), response_id="a")))
        await text(session, "改查上海的明天天气", 2)
        await stop(session)
        await take(stream, AsrCommitRequested)
        assert endpoint.requests == []
    finally:
        await stream.aclose()
        await session.close()


async def test_stable_feedback_does_not_stop_playback_or_call_endpoint():
    from server.realtime.capabilities.turn_manager import AsrDiscardRequested
    from tests.realtime.test_coordinated_turn_manager import Interrupt, stop

    endpoint = Endpoint()
    session = await opened(
        semantic_interruption_classifier=Interrupt(InterruptionLabel.BACKCHANNEL),
        eot_classifier=endpoint,
    )
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "嗯这样挺好的", 1)
        await asyncio.sleep(0.01)
        await stop(session)
        await take(stream, AsrDiscardRequested)
        assert endpoint.requests == []
    finally:
        await stream.aclose()
        await session.close()


async def test_uncertain_first_chunk_waits_for_pending_correction_before_yield():
    from tests.realtime.test_coordinated_turn_manager import stop

    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    class Classifier:
        async def classify_request(self, request):
            requests.append(request)
            if len(requests) == 1:
                return InterruptionClassification(InterruptionLabel.UNCERTAIN, 0.4)
            entered.set()
            await release.wait()
            return InterruptionClassification(InterruptionLabel.CORRECTION, 1)

    session = await opened(semantic_interruption_classifier=Classifier())
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "地点弄错了，我说的是上海。", 1)
        await stop(session)
        await asyncio.wait_for(entered.wait(), 0.2)
        assert not session._input.yield_pending
        assert requests[1].input_state.previous_chunks == ("地点弄错了，",)
        release.set()
        await take(stream, AssistantYieldRequested)
    finally:
        release.set()
        await stream.aclose()
        await session.close()


async def test_compound_continue_feedback_uses_rules_and_does_not_interrupt():
    from server.realtime.capabilities.turn_manager import AsrDiscardRequested
    from tests.realtime.test_coordinated_turn_manager import stop

    class NoModel:
        async def classify_request(self, request):
            raise AssertionError("exact continuation feedback should use rules")

    session = await opened(semantic_interruption_classifier=NoModel())
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "嗯，我在听，你继续讲", 1)
        await stop(session)
        await take(stream, AsrDiscardRequested)
        assert session.snapshot().response_id == "a"
    finally:
        await stream.aclose()
        await session.close()


async def test_stop_word_after_negated_chunk_is_sent_with_context_not_fast_rule():
    requests = []

    class Classifier:
        async def classify_request(self, request):
            requests.append(request)
            return InterruptionClassification(InterruptionLabel.UNCERTAIN, 0.4)

    session = await opened(semantic_interruption_classifier=Classifier())
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "我不是要你，停止。", 1)
        await asyncio.sleep(0.03)
        assert [request.transcript for request in requests] == ["我不是要你，", "停止。"]
        assert requests[1].input_state.previous_chunks == ("我不是要你，",)
        assert session._input.yield_pending is False
    finally:
        await session.close()


async def test_rewritten_accepted_chunk_is_removed_from_previous_context():
    endpoint = Endpoint()
    session = await opened(eot_classifier=endpoint)
    try:
        await start(session)
        await text(session, "先查北京，", 1)
        await asyncio.sleep(0.02)
        assert len(endpoint.requests) == 1
        await text(session, "改查上海。", 2)
        await asyncio.sleep(0.02)
        assert endpoint.requests[-1].text == "改查上海。"
        assert endpoint.requests[-1].input_state.previous_chunks == ()
    finally:
        await session.close()


async def test_injected_rules_control_fast_path_without_calling_model():
    calls = []

    class Rules:
        def match(self, context):
            if context.text == "结束介绍":
                return InterruptionClassification(InterruptionLabel.STOP, 1)
            return None

    class Model:
        async def classify_request(self, request):
            calls.append(request)
            return InterruptionClassification(InterruptionLabel.UNCERTAIN, 0)

    session = await opened(interruption_rules=Rules(), semantic_interruption_classifier=Model())
    stream = session.events()
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "结束介绍", 1)
        await take(stream, AssistantYieldRequested)
        assert calls == []
    finally:
        await stream.aclose()
        await session.close()


async def test_uncertain_overlap_does_not_yield_at_sentence_end_or_recovery():
    from tests.realtime.test_coordinated_turn_manager import Interrupt, stop
    session = await opened(semantic_interruption_classifier=Interrupt(InterruptionLabel.UNCERTAIN))
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=replace(context(), response_id="a")))
        await start(session)
        await text(session, "识别内容不清。", 1)
        await stop(session)
        await asyncio.sleep(0.03)
        assert session._input is not None
        assert not session._input.yield_pending
        await asyncio.sleep(1.05)
        assert session.snapshot().response_id == "a"
        assert session._input.blocked
        assert session._input.rejected_text == "识别内容不清。"
        assert not session.response_delivery_allowed("a")
    finally:
        await session.close()


async def test_before_first_playback_feedback_does_not_cancel_preparing_response():
    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        AsrDiscardRequested,
        ObserveAsrEvent,
        UserTurnCommitted,
    )
    from tests.realtime.test_coordinated_turn_manager import stop
    endpoint = Endpoint()
    session = await opened(eot_classifier=endpoint)
    stream = session.events()
    first = context()
    second = replace(first, generation=first.generation + 1, turn_id="feedback")
    try:
        await start(session, first)
        await text(session, "讲一个故事。", ctx=first)
        await stop(session, first)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="讲一个故事。", reason="final")))
        await take(stream, UserTurnCommitted)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=replace(first, response_id="a"), preparing=True))
        await start(session, second)
        assert session._input is not None and not session._input.yield_pending
        await text(session, "嗯。", ctx=second)
        await stop(session, second)
        await take(stream, AsrDiscardRequested)
        assert session.snapshot().response_id == "a"
        assert len(endpoint.requests) == 1
    finally:
        await stream.aclose()
        await session.close()


async def test_natural_completion_does_not_promote_rule_confirmed_feedback_to_new_turn():
    from server.realtime.capabilities.turn_manager import ObserveSystemResponseCompleted
    from tests.realtime.test_coordinated_turn_manager import stop

    class NoModel:
        async def classify_request(self, request):
            raise AssertionError("Exact feedback should not need a model call")

    session = await opened(semantic_interruption_classifier=NoModel())
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=replace(context(), response_id="a")))
        await start(session)
        await text(session, "哼哼。", 1)
        await stop(session)
        await asyncio.sleep(0.03)
        await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        assert not session.snapshot().commit_pending
        assert session._input is None
    finally:
        await session.close()
