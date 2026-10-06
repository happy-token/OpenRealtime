"""Actor-authorized current-sentence retention, independent from generation cancel."""

import asyncio
import time
from dataclasses import replace

import pytest

from server.realtime.capabilities.asr import AsrTranscriptFinal
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AssistantYieldRequested,
    ObserveAsrEvent,
    ObserveAssistantPlayback,
    ObserveAssistantYielded,
    ObserveSystemResponseStarted,
    UserTurnCommitted,
)
from server.realtime.protocol.playback import ReplyPlayback, SentenceSpan, sentence_identity
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_coordinated_turn_manager import opened, start, stop, take, text


async def prepared():
    session = await opened()
    stream = session.events()
    first = context()
    second = replace(first, turn_id="supplement", generation=first.generation + 1)
    await start(session, first)
    await text(session, "查天气", ctx=first)
    await stop(session, first)
    await take(stream, AsrCommitRequested)
    await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=first, revision=1, text="查天气", reason="final")))
    await take(stream, UserTurnCommitted)
    await session.send(ObserveSystemResponseStarted(response_id="reply", context=first))
    span = SentenceSpan(sentence_id=sentence_identity(first, "response:reply", "第一句。", 0),
        text="第一句。", text_start=0, text_end=4, audio_start_us=0, audio_end_us=1_000_000)
    fact = ReplyPlayback(output_epoch="epoch", speech_id="response:reply", played_audio_end_us=500_000,
        confirmed_text_end=0, observed_at_ns=time.monotonic_ns(), position_precision="sample", current_sentence=span,
        played_position_samples=500, sample_rate_hz=1000)
    await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=fact))
    await start(session, second)
    await text(session, "补充一下，明天也要看。", ctx=second)
    event = await take(stream, AssistantYieldRequested)
    return session, stream, first, second, fact, event


async def test_supplement_permit_waits_for_actual_stop_before_asr_commit():
    session, stream, first, second, fact, event = await prepared()
    try:
        permit = getattr(event, "sentence_permit", None)
        assert permit is not None, "ordinary supplement still cancels the started sentence immediately"
        assert permit.sentence_id == fact.current_sentence.sentence_id
        assert permit.input_version == 1 and permit.reply_version == 1
        assert permit.audio_end_samples == 1000
        assert session.sentence_playback_permit_current(permit)
        assert not session.response_delivery_allowed("reply")
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.sleep(0.02)
        assert not session.snapshot().commit_pending
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, current_sentence=None, terminal=True, played_audio_end_us=800_000,
                played_position_samples=800, observed_at_ns=time.monotonic_ns())))
        await take(stream, AsrCommitRequested)
        assert not session.sentence_playback_permit_current(permit)
    finally:
        await session.close()


async def test_latest_explicit_correction_revokes_one_pending_sentence_without_redeciding_the_stop():
    session, stream, first, second, fact, event = await prepared()
    try:
        permit = getattr(event, "sentence_permit", None)
        assert permit is not None
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await text(session, "不是，刚才那个地方说错了。", revision=2, ctx=second)
        revoked = await take(stream, AssistantYieldRequested)
        assert revoked.revokes_sentence_permit_id == permit.permit_id
        assert revoked.sentence_permit is None
        assert not session.sentence_playback_permit_current(permit)
        assert not session.snapshot().commit_pending
        await stop(session, second)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, current_sentence=None, terminal=True, observed_at_ns=time.monotonic_ns())))
        await take(stream, AsrCommitRequested)
    finally:
        await session.close()


class ControlledAsr:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.commits = []
        self.latest = "補充一下"

    async def open(self, **kwargs):
        return self

    async def send(self, command):
        from server.realtime.capabilities.asr import CommitAsrInput
        if isinstance(command, CommitAsrInput):
            self.commits.append(command)
            await self.queue.put(AsrTranscriptFinal(context=command.context, revision=2, text=self.latest, reason="final"))

    async def events(self):
        while True:
            yield await self.queue.get()

    async def close(self):
        pass


class RecordingBrain:
    def __init__(self):
        self.turns = []

    async def stream(self, turn):
        self.turns.append(turn)
        yield "第一句。第二句。"


@pytest.mark.parametrize("stop_samples", [600, 1000])
@pytest.mark.parametrize("withdrawal", [None, "old_first", "immediate_first"])
@pytest.mark.parametrize("delay_stop_fact", [False, True])
async def test_production_actor_permit_reaches_bridge_and_generates_only_after_actual_heard_frontier(stop_samples, withdrawal, delay_stop_fact):
    from server.realtime import AssistantYieldRequested as CanonicalYield
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
    from server.turn_policy.policy import TurnPolicy
    from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
    from tests.realtime.test_coordinated_turn_manager import Interrupt
    from tests.realtime.test_realtime_websocket_bridge import context as bridge_context
    from tests.realtime.test_reply_playback_observation import playing_core

    class Store(InMemorySpeechDeliveryStore):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.block_once = delay_stop_fact

        async def record_output_stop(self, fact):
            if fact.state == "STOP_CONFIRMED" and self.block_once:
                self.block_once = False
                self.entered.set()
                await self.release.wait()
            return await super().record_output_stop(fact)

    store = Store()
    brain, asr = RecordingBrain(), ControlledAsr()
    asr.latest = "补充一下，明天也要看。"
    manager = CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, semantic_interruption_classifier=Interrupt(),
        asr_idle_stop_ms=15, semantic_interruption_idle_ms=5, recovery_timeout_ms=1000)
    core, bridge = await playing_core(precise_stop=True, brain=brain, asr=asr, turn_manager=manager, managed=True, speech_deliveries=store)
    session = core._input_pipeline._turn_manager
    first = bridge_context()
    second = replace(first, turn_id="supplement", generation=first.generation+1)
    pump = projecting = None
    try:
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id="response:reply",
            generation=1, phase="playing", played_position_samples=500))
        await start(session, second)
        await text(session, asr.latest, ctx=second)
        async with asyncio.timeout(1):
            async for event in bridge._conversation.events():
                await bridge.handle_event(event)
                if isinstance(event, CanonicalYield):
                    break
        async def drain():
            async for event in bridge._conversation.events():
                await bridge.handle_event(event)
        pump = asyncio.create_task(drain())
        request = bridge._transport.frames[-1]
        assert request.sentence_permit is not None
        assert request.sentence_permit.audio_end_samples == 1000
        assert request.sentence_permit.max_wait_ms <= 750
        assert bridge._output_stops[request.stop_command_id].receipt_timeout_s > 1.5
        assert len(brain.turns) == 1
        requests = [request]
        if withdrawal is not None:
            asr.latest = "不是，刚才那个地方说错了。"
            await text(session, asr.latest, revision=2, ctx=second)
            async with asyncio.timeout(1):
                while len(bridge._output_stops) < 2:
                    await asyncio.sleep(.001)
            requests = [entry.request for entry in bridge._output_stops.values()]
            assert requests[1].sentence_permit is None
            if withdrawal == "immediate_first":
                requests.reverse()
        await stop(session, second)
        await asyncio.sleep(0.02)
        assert asr.commits == []
        result = OutputStopResult(output_epoch="epoch", speech_id="response:reply", generation=1,
            stop_command_id=requests[0].stop_command_id, outcome="queue_stopped", played_position_samples=stop_samples)
        if delay_stop_fact:
            projecting = asyncio.create_task(bridge.handle_inbound(result))
            await asyncio.wait_for(store.entered.wait(), 1)
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id="response:reply",
                generation=1, phase="playing", played_position_samples=550))
            assert session.response_revision("reply").playback.observed_at_ns > bridge._output_stops[requests[0].stop_command_id].received_ns
            assert asr.commits == []
            store.release.set()
            await asyncio.wait_for(projecting, 1)
        else:
            await bridge.handle_inbound(result)
        if withdrawal is not None:
            await asyncio.sleep(.02)
            assert not any(frame.type in {"assistant_text", "assistant_speech_text", "assistant_audio_chunk"}
                           and frame.generation == second.generation for frame in bridge._transport.frames)
            assert any(not entry.ready.done() for entry in bridge._output_stops.values())
            await bridge.handle_inbound(OutputStopResult(output_epoch="epoch", speech_id="response:reply", generation=1,
                stop_command_id=requests[1].stop_command_id, outcome="queue_stopped", played_position_samples=stop_samples))
        # The production pumps now commit the latest final transcript and form a response.
        async with asyncio.timeout(1):
            while len(brain.turns) < 2:
                await asyncio.sleep(0.001)
        assert brain.turns[1].text == "说两句\n" + asr.latest
        async with asyncio.timeout(1):
            while not any(frame.type == "assistant_speech_text" and frame.generation == second.generation
                          for frame in bridge._transport.frames):
                await asyncio.sleep(.001)
        if stop_samples < 1000:
            assert "第一句。第二句。" not in (brain.turns[1].conversation_context or "")
        else:
            assert "第一句。" in (brain.turns[1].conversation_context or "")
            assert "第二句。" not in (brain.turns[1].conversation_context or "")
    finally:
        store.release.set()
        if projecting is not None:
            await asyncio.gather(projecting, return_exceptions=True)
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        await bridge.close()
        await bridge._conversation.close()

@pytest.mark.parametrize("invalid", ["context_response", "scope", "generation", "epoch", "speech", "rate", "time", "position"])
async def test_wrong_or_regressing_terminal_cannot_release_physical_wait(invalid):
    session, stream, first, second, fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        target = first
        terminal = replace(fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())
        if invalid == "context_response":
            target = replace(first, response_id="foreign-response")
        elif invalid == "scope":
            target = replace(first, voice_session_id="another-session")
        elif invalid == "generation":
            target = replace(first, generation=first.generation+1)
        elif invalid == "epoch":
            terminal = replace(terminal, output_epoch="another-epoch")
        elif invalid == "speech":
            terminal = replace(terminal, speech_id="another-speech")
        elif invalid == "rate":
            terminal = replace(terminal, sample_rate_hz=2000, played_position_samples=1000)
        elif invalid == "time":
            terminal = replace(terminal, observed_at_ns=fact.observed_at_ns-1)
        elif invalid == "position":
            terminal = replace(terminal, played_audio_end_us=400_000, played_position_samples=400)
        command = ObserveAssistantPlayback(context=target, response_id="reply", fact=terminal)
        if invalid == "scope":
            with pytest.raises(ValueError, match="another session"):
                await session.send(command)
        else:
            await session.send(command)
        assert not session.snapshot().commit_pending
        assert not session.response_delivery_allowed("reply")
        assert session.sentence_playback_permit_current(event.sentence_permit)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())))
        await take(stream, AsrCommitRequested)
    finally:
        await session.close()


async def test_replacement_delivery_stays_blocked_until_original_target_physical_receipt():
    session, stream, first, second, fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await session.send(ObserveSystemResponseStarted(response_id="replacement", context=first, preparing=True))
        assert not session.response_delivery_allowed("replacement")
        await asyncio.sleep(.02)
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="replacement")))
        await stop(session, second)
        assert session._input.sentence_wait == event.sentence_permit
        assert not session.snapshot().commit_pending
        revoked = await take(stream, AssistantYieldRequested)
        assert revoked.revokes_sentence_permit_id == event.sentence_permit.permit_id
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())))
        assert session._input.sentence_wait is None
    finally:
        await session.close()


async def test_stale_permit_revocation_cannot_cancel_a_completed_buffered_replacement():
    from server.realtime.speech.delivery import SpeechDeliveryStatus
    from tests.realtime.test_reply_playback_observation import playing_core

    core, bridge = await playing_core(precise_stop=True)
    try:
        session = core._input_pipeline._turn_manager
        assert core._active_response_id is None
        assert "response:reply" in core._unsettled_model_speech_ids
        await session._outbox.put(AssistantYieldRequested(context=replace(core._context, response_id="old-reply"),
            reason="sentence_permit_deadline", revokes_sentence_permit_id="old-permit"))
        async with asyncio.timeout(1):
            async for event in core.events():
                await bridge.handle_event(event)
                if getattr(event, "revokes_sentence_permit_id", None) == "old-permit":
                    break
        await asyncio.sleep(.01)
        assert "response:reply" in core._unsettled_model_speech_ids
        assert (await core._speech_deliveries.get("response:reply")).status is SpeechDeliveryStatus.ACTIVE
    finally:
        await bridge.close()
        await core.close()

@pytest.mark.parametrize("change", ["unknown", "next_sentence", "rewrite", "append_correction", "append_stop"])
async def test_new_evidence_revokes_one_sentence_without_releasing_physical_wait(change):
    session, stream, first, second, fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        if change in {"rewrite", "append_correction", "append_stop"}:
            updated_text = "补充一下，请立刻停止，不要再说了。" if change == "rewrite" else (
                "补充一下，明天也要看。" + ("不是，刚才我说错了。" if change == "append_correction" else "别说了。"))
            await text(session, updated_text, revision=2, ctx=second)
        else:
            updated = replace(fact, observed_at_ns=time.monotonic_ns(), current_sentence=None)
            if change == "unknown":
                updated = replace(updated, position_precision="unknown", output_epoch=None,
                                  played_position_samples=None, sample_rate_hz=None)
            else:
                updated = replace(updated, played_audio_end_us=1_000_000, played_position_samples=1000)
            await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=updated))
        revoked = await take(stream, AssistantYieldRequested)
        assert revoked.revokes_sentence_permit_id == event.sentence_permit.permit_id
        assert not session.sentence_playback_permit_current(event.sentence_permit)
        assert session._input.sentence_wait == event.sentence_permit
        await stop(session, second)
        assert not session.snapshot().commit_pending
    finally:
        await session.close()


async def test_direct_invalidation_keeps_bounded_failure_exit_without_any_physical_stop_receipt():
    from server.realtime.capabilities.turn_manager import ObserveResponseInvalidated

    session, stream, first, second, _fact, _event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await session.send(ObserveResponseInvalidated(context=first, response_id="reply", reason="manual_cancel"))
        await take(stream, AssistantYieldRequested)
        await stop(session, second)
        async with asyncio.timeout(1):
            while not session._actor.done():
                await asyncio.sleep(.001)
        assert isinstance(session._failure, TimeoutError)
        assert "sentence_stop_ack" in str(session._failure)
        assert not session.snapshot().commit_pending
    finally:
        await session.close()

async def test_ordinary_append_keeps_original_permit_and_does_not_refresh_deadline():
    session, _stream, _first, second, _fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await text(session, "补充一下，明天也要看。还有周末的。", revision=2, ctx=second)
        assert session._input.sentence_wait == event.sentence_permit
        assert not session._input.sentence_revoked
        assert session.sentence_playback_permit_current(event.sentence_permit)
    finally:
        await session.close()


async def test_original_terminal_clock_before_late_playing_projection_still_releases_wait():
    session, stream, first, second, fact, _event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        terminal_ns = time.monotonic_ns()
        late = replace(fact, observed_at_ns=terminal_ns+1, played_audio_end_us=550_000, played_position_samples=550)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=late))
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, terminal=True, current_sentence=None, observed_at_ns=terminal_ns,
                         played_audio_end_us=600_000, played_position_samples=600)))
        await take(stream, AsrCommitRequested)
        assert session.response_revision("reply").playback.observed_at_ns == terminal_ns
        assert session.response_revision("reply").playback.terminal
    finally:
        await session.close()

@pytest.mark.parametrize("owner", ["cascade", "pipeline", "managed", "control", "tools", "delegation", "endpoint"])
def test_closing_owner_cannot_reuse_authority_from_a_still_open_delegate(owner):
    from server.realtime.capabilities.input_pipeline import CascadedInputPipeline
    from server.realtime.cascaded.engine import CascadedRealtimeConversation
    from server.realtime.control_plane import RealtimeTurnController
    from server.realtime.delegation_controller import RealtimeDelegationController
    from server.realtime.runtime import ManagedRealtimeConversation
    from server.realtime.tool_controller import RealtimeToolController
    from server.voice_session.endpoint_bridge import _ReconnectableConversation

    class StillOpenDelegate:
        def sentence_playback_permit_current(self, permit):
            return True

    owners = {
        "cascade": (CascadedRealtimeConversation, "_input_pipeline"),
        "pipeline": (CascadedInputPipeline, "_turn_manager"),
        "managed": (ManagedRealtimeConversation, "_conversation"),
        "control": (RealtimeTurnController, "_conversation"),
        "tools": (RealtimeToolController, "_conversation"),
        "delegation": (RealtimeDelegationController, "_conversation"),
        "endpoint": (_ReconnectableConversation, "_current"),
    }
    cls, attachment = owners[owner]
    closing = object.__new__(cls)
    setattr(closing, attachment, StillOpenDelegate())
    closing._closed = False
    assert closing.sentence_playback_permit_current(None)
    # Owner.close/reconfigure flips its latch before delegate I/O can finish.
    closing._closed = True
    assert not closing.sentence_playback_permit_current(None)

@pytest.mark.parametrize("replacement", [False, True])
async def test_unknown_progress_advances_wait_frontier_and_regressing_stop_cannot_release(replacement):
    session, stream, first, second, fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        if replacement:
            await session.send(ObserveSystemResponseStarted(response_id="replacement", context=first, preparing=True))
        unknown = replace(fact, played_audio_end_us=700_000, position_precision="unknown", output_epoch=None,
                          played_position_samples=None, sample_rate_hz=None, current_sentence=None,
                          observed_at_ns=time.monotonic_ns())
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=unknown))
        await take(stream, AssistantYieldRequested)
        regressing = replace(fact, terminal=True, current_sentence=None, played_audio_end_us=600_000,
                             played_position_samples=600, observed_at_ns=time.monotonic_ns())
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=regressing))
        if not replacement:
            assert not session.response_revision("reply").playback.terminal
        assert not session.snapshot().commit_pending
        assert session._input.sentence_wait == event.sentence_permit
        if replacement:
            async with asyncio.timeout(.5):
                async for pending in stream:
                    if isinstance(pending, AssistantYieldRequested) and pending.context.response_id == "replacement":
                        break
            await session.send(ObserveAssistantYielded(context=replace(second, response_id="replacement")))
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(unknown, terminal=True, output_epoch="epoch", observed_at_ns=time.monotonic_ns())))
        await take(stream, AsrCommitRequested)
    finally:
        await session.close()

async def test_a_new_sentence_permit_does_not_inherit_a_previous_targets_revoked_latch():
    from server.realtime.capabilities.turn_manager import ObserveResponseInvalidated

    session, stream, first, second, fact, event = await prepared()
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await session.send(ObserveResponseInvalidated(context=first, response_id="reply", reason="manual_cancel"))
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply",
            fact=replace(fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())))
        assert session._input.sentence_revoked
        await session.send(ObserveSystemResponseStarted(response_id="replacement", context=first, preparing=True))
        span = replace(fact.current_sentence, sentence_id=sentence_identity(first, "response:replacement", "第一句。", 0))
        await session.send(ObserveAssistantPlayback(context=first, response_id="replacement",
            fact=replace(fact, speech_id="response:replacement", current_sentence=span,
                         played_audio_end_us=900_000, played_position_samples=900, observed_at_ns=time.monotonic_ns())))
        granted = await take(stream, AssistantYieldRequested)
        assert granted.sentence_permit is not None
        assert granted.sentence_permit.permit_id != event.sentence_permit.permit_id
        assert not session._input.sentence_revoked
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="replacement")))
        await stop(session, second)
        expired = await take(stream, AssistantYieldRequested)
        assert expired.revokes_sentence_permit_id == granted.sentence_permit.permit_id
        async with asyncio.timeout(1):
            while not session._actor.done():
                await asyncio.sleep(.001)
        assert "sentence_stop_ack" in str(session._failure)
        assert not session.snapshot().commit_pending
    finally:
        await session.close()


async def test_active_generation_cancellation_preserves_actor_current_sentence_permit():
    from datetime import UTC, datetime

    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemKind,
        ConversationItemStatus,
        TextContent,
    )
    from server.conversation_journal.models import item_from_draft
    from server.realtime import AssistantYieldRequested as CanonicalYield
    from server.realtime import ProjectCommittedItem, RequestResponse, SpeechTextAlignment
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.transport import RealtimeWebSocketFrameBridge
    from server.turn_policy.policy import TurnPolicy
    from server.voice_session.protocol import PlaybackProgressV2
    from tests.realtime.test_coordinated_turn_manager import Interrupt
    from tests.realtime.test_input_association_production import wait_for
    from tests.realtime.test_realtime_websocket_bridge import RecordingTransport
    from tests.realtime.test_realtime_websocket_bridge import context as bridge_context
    from tests.realtime.test_reply_playback_observation import Provider
    from tests.realtime.test_reply_revision_production_delivery import open_core

    class ActiveBrain:
        async def stream(self, turn):
            yield "第一句。第二句。"
            await asyncio.Event().wait()

    class Duplex:
        async def synthesize_duplex(self, texts):
            async for value in texts:
                async for chunk in Provider().synthesize_stream(value):
                    yield chunk

    first = bridge_context()
    second = replace(first, turn_id="supplement", generation=first.generation+1)
    manager = CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, semantic_interruption_classifier=Interrupt(),
        asr_idle_stop_ms=15, semantic_interruption_idle_ms=5, recovery_timeout_ms=1000)
    core = await open_core(brain=ActiveBrain(), tts=Duplex(), asr=ControlledAsr(),
        turn_manager=manager, interaction_context=first)
    bridge = RealtimeWebSocketFrameBridge(context=first, conversation=core, transport=RecordingTransport(),
        output_epoch="epoch", precise_output_stop=True)
    stream = core.events()
    try:
        draft = ConversationItemDraft(item_id="user", context=first, kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED, producer="test", content=(TextContent("说两句"),))
        await core.send(ProjectCommittedItem(command_id="user", idempotency_key="user", context=first,
            item=item_from_draft(draft, sequence=1, recorded_at=datetime.now(UTC))))
        await core.send(RequestResponse(command_id="request", idempotency_key="request", context=first,
            response_id="reply", minimum_thread_sequence=1))
        async with asyncio.timeout(1):
            async for event in stream:
                await bridge.handle_event(event)
                if isinstance(event, SpeechTextAlignment) and event.sentence is not None:
                    break
        assert core._response_task is not None and not core._response_task.done()
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id="response:reply",
            generation=1, phase="playing", played_position_samples=500))
        session = core._input_pipeline._turn_manager
        await start(session, second)
        await text(session, "补充一下，明天也要看。", ctx=second)
        async with asyncio.timeout(1):
            async for event in stream:
                await bridge.handle_event(event)
                if isinstance(event, CanonicalYield) and event.sentence_permit is not None:
                    permit = event.sentence_permit
                    break
        await wait_for(lambda: core._response_task is None)
        assert session.sentence_playback_permit_current(permit)
        assert not session._input.sentence_revoked
        assert not [event for event in core._events._queue if isinstance(event, CanonicalYield)]
        assert len(bridge._output_stops) == 1
        wire = next(iter(bridge._output_stops.values())).request.sentence_permit
        assert wire is not None and wire.permit_id == permit.permit_id
        assert wire.audio_end_samples == permit.audio_end_samples
        assert 0 < wire.max_wait_ms <= 750
    finally:
        await stream.aclose()
        await bridge.close()
        await core.close()
