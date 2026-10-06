"""Bridge -> production model speech -> actor playback identity and position."""

import asyncio
from datetime import UTC, datetime

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.conversation_journal.models import item_from_draft
from server.realtime import ProjectCommittedItem, RequestResponse, ResponseCompleted
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.speech.plugins.doubao_tts_direct import _alignment_chunks
from server.speech.tts import SynthesizedAudioChunk
from server.voice_session.protocol import PlaybackProgressV2
from tests.realtime.test_realtime_websocket_bridge import RecordingTransport, context
from tests.realtime.test_reply_revision_production_delivery import open_core


class Brain:
    async def stream(self, turn):
        yield "第一句。第二句。"


class Provider:
    async def synthesize_stream(self, text):
        yield SynthesizedAudioChunk(pcm16=b"\x00\x00" * 2000, sample_rate_hz=1000, is_final=False)
        for sentence, start in [("第一句。", 0), ("第二句。", 1)]:
            for chunk in _alignment_chunks(
                {
                    "text": sentence,
                    "words": [
                        {"word": sentence, "startTime": start, "endTime": start + 1},
                    ],
                },
                1000,
            ):
                yield chunk


async def playing_core(*, speech_deliveries=None, precise_stop=False):
    core = await open_core(
        brain=Brain(),
        tts=Provider(),
        interaction_context=context(),
        speech_deliveries=speech_deliveries,
    )
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=core,
        transport=RecordingTransport(),
        output_epoch="epoch",
        precise_output_stop=precise_stop,
    )
    await core.send(
        ProjectCommittedItem(
            command_id="user",
            idempotency_key="user",
            context=context(),
            item=item_from_draft(
                ConversationItemDraft(
                    item_id="user",
                    context=context(),
                    kind=ConversationItemKind.USER_INPUT,
                    status=ConversationItemStatus.COMPLETED,
                    producer="test",
                    content=(TextContent("说两句"),),
                ),
                sequence=1,
                recorded_at=datetime.now(UTC),
            ),
        )
    )
    await core.send(
        RequestResponse(
            command_id="request",
            idempotency_key="request",
            context=context(),
            response_id="reply",
            minimum_thread_sequence=1,
        )
    )
    async with asyncio.timeout(1):
        async for event in core.events():
            await bridge.handle_event(event)
            if isinstance(event, ResponseCompleted):
                break
    return core, bridge


async def test_actual_renderer_position_reaches_actor_with_current_sentence_and_epoch():
    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        reply = core._input_pipeline.response_revision("reply")
        fact = getattr(reply, "playback", None)
        assert fact is not None, (
            "actor lost the actual playback target and retained only playback_started"
        )
        assert fact.output_epoch == "epoch"
        assert fact.speech_id == "response:reply"
        assert fact.played_audio_end_us == 500_000
        assert getattr(fact, "played_position_samples", None) == 500
        assert getattr(fact, "sample_rate_hz", None) == 1000
        assert fact.confirmed_text_end == 0
        assert fact.current_sentence.text == "第一句。"
        assert fact.current_sentence.audio_end_us == 1_000_000
        assert not fact.terminal
        assert fact.observed_at_ns > 0
        assert reply.playback_started
    finally:
        await core.close()


async def test_current_sentence_tracks_actual_clock_and_terminal_cannot_reopen():
    core, bridge = await playing_core()
    try:
        for samples, sentence in [(0, None), (500, "第一句。"), (1000, None), (1500, "第二句。")]:
            await bridge.handle_inbound(
                PlaybackProgressV2(
                    output_epoch="epoch",
                    speech_id="response:reply",
                    generation=1,
                    phase="playing",
                    played_position_samples=samples,
                )
            )
            fact = core._input_pipeline.response_revision("reply").playback
            assert (fact.current_sentence.text if fact.current_sentence else None) == sentence
            assert fact.position_precision == "sample"
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="finished",
                played_position_samples=2000,
            )
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.terminal and fact.current_sentence is None
        assert fact.confirmed_text_end == 8
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=1500,
            )
        )
        assert core._input_pipeline.response_revision("reply").playback == fact
    finally:
        await core.close()


async def test_old_epoch_and_wrong_target_never_reach_actor_current_sentence():
    core, bridge = await playing_core()
    try:
        for epoch, speech, generation in [
            ("expired", "response:reply", 1),
            ("epoch", "old-speech", 1),
            ("epoch", "response:reply", 2),
        ]:
            await bridge.handle_inbound(
                PlaybackProgressV2(
                    output_epoch=epoch,
                    speech_id=speech,
                    generation=generation,
                    phase="playing",
                    played_position_samples=500,
                )
            )
            assert core._input_pipeline.response_revision("reply").playback is None
    finally:
        await core.close()


def test_ledger_playback_fact_keeps_all_identity_and_monotonic_terminal_boundaries():
    from dataclasses import replace

    from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
    from server.realtime.protocol.playback import ReplyPlayback, SentenceSpan, sentence_identity
    from tests.realtime.test_reply_revision_controller import commit

    ledger = ReplyRevisionController()
    commit(ledger, ctx=context())
    ledger.bind_response("reply", context())
    span = SentenceSpan(
        sentence_id=sentence_identity(context(), "response:reply", "第一句。", 0),
        text="第一句。",
        text_start=0,
        text_end=4,
        audio_start_us=0,
        audio_end_us=1_000_000,
    )
    fact = ReplyPlayback(
        output_epoch="epoch",
        speech_id="response:reply",
        played_audio_end_us=500_000,
        confirmed_text_end=0,
        observed_at_ns=10,
        position_precision="sample",
        played_position_samples=500,
        sample_rate_hz=1000,
        current_sentence=span,
    )
    assert ledger.observe_playback_fact("reply", context(), fact)
    for field in ["tenant_id", "user_id", "device_id", "voice_session_id", "thread_id", "turn_id"]:
        assert not ledger.observe_playback_fact(
            "reply", replace(context(), **{field: "wrong"}), replace(fact, observed_at_ns=11)
        )
    assert not ledger.observe_playback_fact("reply", replace(context(), generation=2), fact)
    assert not ledger.observe_playback_fact("reply", replace(context(), response_id="wrong"), fact)
    assert not ledger.observe_playback_fact("reply", context(), replace(fact, speech_id="wrong"))
    assert not ledger.observe_playback_fact(
        "reply", context(), replace(fact, output_epoch="expired", observed_at_ns=11)
    )
    assert not ledger.observe_playback_fact(
        "reply",
        context(),
        replace(fact, played_audio_end_us=400_000, played_position_samples=400, observed_at_ns=11),
    )
    assert not ledger.observe_playback_fact("reply", context(), replace(fact, observed_at_ns=9))
    assert ledger.reply.playback == fact
    # Repeated position reports do not refresh the age of an unchanged sample.
    assert not ledger.observe_playback_fact("reply", context(), replace(fact, observed_at_ns=11))
    ledger.revoke("reply", reason="input_replaced")
    terminal = replace(fact, observed_at_ns=12, terminal=True, current_sentence=None)
    assert ledger.observe_playback_fact("reply", context(), terminal)
    assert not ledger.delivery_allowed("reply")
    assert not ledger.observe_playback_fact("reply", context(), replace(fact, observed_at_ns=13))
    assert ledger.reply.playback.observed_at_ns == terminal.observed_at_ns
    ledger.observe_playback_fact(
        "reply",
        context(),
        replace(fact, observed_at_ns=13, played_audio_end_us=600_000, played_position_samples=600),
    )
    assert ledger.reply.playback.terminal and ledger.reply.playback.current_sentence is None
    assert ledger.reply.playback.observed_at_ns == terminal.observed_at_ns
    assert not ledger.delivery_allowed("reply")
    ledger.close()
    assert not ledger.observe_playback_fact(
        "reply", context(), replace(terminal, observed_at_ns=14)
    )


def test_estimated_receipt_clears_current_sentence_without_losing_known_target():
    from dataclasses import replace

    from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
    from server.realtime.protocol.playback import ReplyPlayback, SentenceSpan, sentence_identity
    from tests.realtime.test_reply_revision_controller import commit

    ledger = ReplyRevisionController()
    commit(ledger, ctx=context())
    ledger.bind_response("reply", context())
    span = SentenceSpan(
        sentence_id=sentence_identity(context(), "response:reply", "第一句。", 0),
        text="第一句。",
        text_start=0,
        text_end=4,
        audio_start_us=0,
        audio_end_us=1_000_000,
    )
    fact = ReplyPlayback(
        output_epoch="epoch",
        speech_id="response:reply",
        played_audio_end_us=500_000,
        confirmed_text_end=0,
        observed_at_ns=10,
        position_precision="sample",
        played_position_samples=500,
        sample_rate_hz=1000,
        current_sentence=span,
    )
    ledger.observe_playback_fact("reply", context(), fact)
    unknown = replace(
        fact,
        output_epoch=None,
        current_sentence=None,
        position_precision="unknown",
        played_position_samples=None,
        sample_rate_hz=None,
        observed_at_ns=11,
    )
    assert ledger.observe_playback_fact("reply", context(), unknown)
    assert ledger.reply.playback.position_precision == "unknown"
    assert ledger.reply.playback.output_epoch == "epoch"
    assert ledger.reply.playback.current_sentence is None


async def test_duplicate_v2_receipt_is_idempotent_and_does_not_refresh_position_age():
    core, bridge = await playing_core()
    try:
        frame = PlaybackProgressV2(
            output_epoch="epoch",
            speech_id="response:reply",
            generation=1,
            phase="playing",
            played_position_samples=500,
        )
        await bridge.handle_inbound(frame)
        fact = core._input_pipeline.response_revision("reply").playback
        await bridge.handle_inbound(frame)
        assert core._input_pipeline.response_revision("reply").playback == fact
    finally:
        await core.close()


@pytest.mark.parametrize("late_projects_last", [False, True])
@pytest.mark.parametrize("larger_late_position", [False, True])
async def test_delayed_stop_persistence_keeps_original_receipt_clock_and_beats_late_playing_projection(
    late_projects_last,
    larger_late_position,
):
    from dataclasses import replace

    from server.realtime import AssistantYieldRequested
    from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
    from server.voice_session.protocol import OutputStopResult

    class Store(InMemorySpeechDeliveryStore):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.late_entered, self.late_release = asyncio.Event(), asyncio.Event()
            self.block_next_progress = False

        async def record_output_stop(self, fact):
            if fact.state == "STOP_CONFIRMED":
                self.entered.set()
                await self.release.wait()
            return await super().record_output_stop(fact)

        async def report_progress(self, speech_id, **kwargs):
            if self.block_next_progress:
                self.block_next_progress = False
                self.late_entered.set()
                await self.late_release.wait()
            return await super().report_progress(speech_id, **kwargs)

    store = Store()
    core, bridge = await playing_core(speech_deliveries=store, precise_stop=True)
    projecting = None
    late_projecting = None
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        await bridge.handle_event(
            AssistantYieldRequested(
                event_id="yield",
                context=replace(context(), response_id="reply"),
                conversation_sequence=100,
                occurred_at=datetime.now(UTC),
                reason="barge_in_floor_claim",
            )
        )
        request = bridge._transport.frames[-1]
        projecting = asyncio.create_task(
            bridge.handle_inbound(
                OutputStopResult(
                    output_epoch="epoch",
                    speech_id="response:reply",
                    generation=1,
                    stop_command_id=request.stop_command_id,
                    outcome="queue_stopped",
                    played_position_samples=600,
                )
            )
        )
        await asyncio.wait_for(store.entered.wait(), 0.5)
        stop = bridge._output_stops[request.stop_command_id]
        # A pre-stop progress packet can be processed while its receipt is being persisted.
        late_frame = PlaybackProgressV2(
            output_epoch="epoch",
            speech_id="response:reply",
            generation=1,
            phase="playing",
            played_position_samples=650
            if larger_late_position
            else 600
            if late_projects_last
            else 550,
        )
        if late_projects_last:
            store.block_next_progress = True
            late_projecting = asyncio.create_task(bridge.handle_inbound(late_frame))
            await asyncio.wait_for(store.late_entered.wait(), 0.5)
        else:
            await bridge.handle_inbound(late_frame)
            assert (
                core._input_pipeline.response_revision("reply").playback.observed_at_ns
                > stop.received_ns
            )
        store.release.set()
        await asyncio.wait_for(asyncio.shield(stop.ready), 0.5)
        store.late_release.set()
        if late_projecting is not None:
            await asyncio.wait_for(late_projecting, 0.5)
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.terminal and fact.current_sentence is None
        assert fact.played_audio_end_us == (650_000 if larger_late_position else 600_000)
        assert fact.position_precision == ("unknown" if larger_late_position else "sample")
        assert fact.observed_at_ns == stop.received_ns
    finally:
        store.release.set()
        store.late_release.set()
        if projecting is not None:
            await asyncio.gather(projecting, return_exceptions=True)
        if late_projecting is not None:
            await asyncio.gather(late_projecting, return_exceptions=True)
        await bridge.close()
        await core.close()


async def test_actual_journal_playback_evidence_does_not_duplicate_large_sentence_text():
    import hashlib
    import json
    import time

    from server.conversation_journal import InMemoryConversationJournal
    from server.conversation_journal.input_evidence import read_input_evidence
    from server.realtime.capabilities import ObserveAssistantPlayback, ObserveSystemResponseStarted
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.protocol.playback import ReplyPlayback, SentenceSpan, sentence_identity
    from server.turn_policy.policy import TurnPolicy

    journal = InMemoryConversationJournal()
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy, input_evidence_journal=journal
    ).open(context=context())
    text = "长" * 80_000
    sentence = SentenceSpan(
        sentence_id=sentence_identity(context(), "response:reply", text, 0),
        text=text,
        text_start=0,
        text_end=len(text),
        audio_start_us=0,
        audio_end_us=1_000_000,
    )
    try:
        await session.send(
            ObserveSystemResponseStarted(response_id="reply", context=context(), preparing=True)
        )
        await session.send(
            ObserveAssistantPlayback(
                context=context(),
                response_id="reply",
                fact=ReplyPlayback(
                    output_epoch="epoch",
                    speech_id="response:reply",
                    played_audio_end_us=500_000,
                    confirmed_text_end=0,
                    observed_at_ns=time.monotonic_ns(),
                    position_precision="sample",
                    played_position_samples=500,
                    sample_rate_hz=1000,
                    current_sentence=sentence,
                ),
            )
        )
        assert session.response_delivery_allowed("reply")
        await session.invalidate_response("reply", context=context(), reason="explicit_stop")
        assert session._evidence.failure is None
    finally:
        await session.close()
    evidence = await read_input_evidence(journal, context())
    playback = next(
        r["detail"]
        for r in evidence["records"]
        if r["detail"]["event"] == "reply_playback_observed"
    )
    invalidation = next(
        r["detail"] for r in evidence["records"] if r["detail"]["event"] == "reply_invalidated"
    )
    for record in (playback, invalidation["playback"]):
        assert "text" not in record["current_sentence"]
        assert record["current_sentence"]["text_length"] == 80_000
        assert (
            record["current_sentence"]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        )
    assert len(json.dumps(evidence, ensure_ascii=False).encode()) < 10_000


async def test_external_speech_fact_binds_delivery_lease_and_keeps_source_context():
    from dataclasses import replace

    from server.realtime import AppendSpeechText, CommitSpeech, SpeechAudioCompleted, StartSpeech

    source = replace(context(), response_id="source-response")
    core = await open_core(tts=Provider(), interaction_context=context())
    bridge = RealtimeWebSocketFrameBridge(
        context=context(), conversation=core, transport=RecordingTransport(), output_epoch="epoch"
    )
    try:
        await core.send(
            StartSpeech(
                command_id="start", idempotency_key="start", context=source, speech_id="direct"
            )
        )
        await core.send(
            AppendSpeechText(
                command_id="text",
                idempotency_key="text",
                context=source,
                speech_id="direct",
                text_sequence=1,
                delta="第一句。第二句。",
            )
        )
        await core.send(
            CommitSpeech(
                command_id="commit", idempotency_key="commit", context=source, speech_id="direct"
            )
        )
        async with asyncio.timeout(1):
            async for event in core.events():
                await bridge.handle_event(event)
                if isinstance(event, SpeechAudioCompleted):
                    break
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="direct",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        reply = core._input_pipeline.response_revision("direct")
        assert reply.playback.current_sentence.text == "第一句。"
        assert reply.playback.output_epoch == "epoch" and reply.playback.speech_id == "direct"
        assert core._input_pipeline.response_revision("source-response") is None
    finally:
        await core.close()


def test_known_sentence_does_not_rehash_each_sample_and_rejects_boundary_reuse(monkeypatch):
    from dataclasses import replace

    import pytest

    from server.realtime.capabilities import reply_revision_controller as module
    from server.realtime.protocol.playback import ReplyPlayback, SentenceSpan, sentence_identity
    from tests.realtime.test_reply_revision_controller import commit

    ledger = module.ReplyRevisionController()
    commit(ledger, ctx=context())
    ledger.bind_response("reply", context())
    sentence = SentenceSpan(
        sentence_id=sentence_identity(context(), "response:reply", "第一句。", 0),
        text="第一句。",
        text_start=0,
        text_end=4,
        audio_start_us=0,
        audio_end_us=1_000_000,
    )
    fact = ReplyPlayback(
        output_epoch="epoch",
        speech_id="response:reply",
        played_audio_end_us=100_000,
        confirmed_text_end=0,
        observed_at_ns=10,
        position_precision="sample",
        played_position_samples=25000,
        sample_rate_hz=250000,
        current_sentence=sentence,
    )
    ledger.observe_playback_fact("reply", context(), fact)

    def unexpected_hash(*args):
        raise AssertionError("sample tick rehashed an unchanged immutable sentence")

    monkeypatch.setattr(module, "sentence_identity", unexpected_hash)
    for index in range(1, 100):
        ledger.observe_playback_fact(
            "reply",
            context(),
            replace(
                fact,
                played_audio_end_us=100_000 + index * 4,
                played_position_samples=25000 + index,
                observed_at_ns=10 + index,
            ),
        )
    with pytest.raises(ValueError, match="reused"):
        ledger.observe_playback_fact(
            "reply",
            context(),
            replace(
                fact,
                played_audio_end_us=200_000,
                played_position_samples=50000,
                observed_at_ns=120,
                current_sentence=replace(sentence, audio_end_us=2_000_000),
            ),
        )


async def test_v2_regression_cannot_invent_a_current_sample_from_a_monotonic_microsecond_frontier():
    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        before = core._input_pipeline.response_revision("reply").playback
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=400,
            )
        )
        assert core._input_pipeline.response_revision("reply").playback == before
    finally:
        await core.close()


async def test_v2_sample_position_is_bounded_by_sent_pcm_and_retained_on_stop():
    from dataclasses import replace

    from server.realtime import AssistantYieldRequested
    from server.voice_session.protocol import OutputStopResult

    core, bridge = await playing_core(precise_stop=True)
    try:
        await bridge.handle_event(
            AssistantYieldRequested(
                event_id="yield",
                context=replace(context(), response_id="reply"),
                conversation_sequence=100,
                occurred_at=datetime.now(UTC),
                reason="barge_in_floor_claim",
            )
        )
        request = bridge._transport.frames[-1]
        await bridge.handle_inbound(
            OutputStopResult(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                stop_command_id=request.stop_command_id,
                outcome="queue_stopped",
                played_position_samples=100_000,
            )
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.terminal
        assert getattr(fact, "played_position_samples", None) == 2000
        assert getattr(fact, "sample_rate_hz", None) == 1000
        assert fact.played_audio_end_us == 2_000_000
    finally:
        await bridge.close()
        await core.close()


@pytest.mark.parametrize("kind", ["command", "fact"])
@pytest.mark.parametrize(
    "samples,rate",
    [
        (None, 1000),
        (500, None),
        (True, 1000),
        (500, True),
        (500.0, 1000),
        (500, 1000.0),
        (-1, 1000),
        (500, 0),
        (500, 384001),
        (2**53, 1000),
        (400, 1000),
    ],
)
def test_sample_clock_requires_strict_paired_fields_and_matching_microseconds(kind, samples, rate):
    from server.realtime.protocol.commands import ReportPlaybackProgress
    from server.realtime.protocol.playback import ReplyPlayback

    with pytest.raises(ValueError, match="sample|clock"):
        if kind == "command":
            ReportPlaybackProgress(
                command_id="sample",
                idempotency_key="sample",
                context=context(),
                speech_id="response:reply",
                output_epoch="epoch",
                observed_at_ns=10,
                played_audio_end_us=500_000,
                delivered_text_end=0,
                played_position_samples=samples,
                sample_rate_hz=rate,
            )
        else:
            ReplyPlayback(
                output_epoch="epoch",
                speech_id="response:reply",
                played_audio_end_us=500_000,
                confirmed_text_end=0,
                observed_at_ns=10,
                position_precision="sample",
                played_position_samples=samples,
                sample_rate_hz=rate,
            )


def test_sample_clock_uses_cumulative_integer_rounding_at_large_safe_positions():
    from fractions import Fraction

    from server.core.playback import sample_position_us

    for rate in [1000, 16000, 44100, 48000, 384000]:
        for position in [0, 1, 3, 44101, 2**53 - 1]:
            assert sample_position_us(position, rate) == round(Fraction(position * 1_000_000, rate))
    assert sample_position_us(3, 44100) == 68  # Three rounded chunks would incorrectly yield69.


async def test_terminal_sample_regression_keeps_stop_fact_but_drops_current_sentence_certainty():
    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="stopped",
                played_position_samples=400,
            )
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.terminal
        assert fact.played_audio_end_us == 500_000
        assert fact.played_position_samples is None and fact.sample_rate_hz is None
        assert fact.position_precision == "unknown" and fact.current_sentence is None
    finally:
        await core.close()


async def test_legacy_receipt_does_not_inherit_a_stale_exact_sample_clock():
    from server.transport.frames import PlaybackProgressFrame

    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        await bridge.handle_inbound(
            PlaybackProgressFrame(generation=1, finished=False, played_audio_end_us=500_000)
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.output_epoch == "epoch" and fact.position_precision == "unknown"
        assert fact.played_position_samples is None and fact.sample_rate_hz is None
    finally:
        await core.close()


def test_same_epoch_rate_changes_cannot_reinterpret_the_current_sample_clock():
    from dataclasses import replace

    from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
    from server.realtime.protocol.playback import ReplyPlayback
    from tests.realtime.test_reply_revision_controller import commit

    ledger = ReplyRevisionController()
    commit(ledger, ctx=context())
    ledger.bind_response("reply", context())
    fact = ReplyPlayback(
        output_epoch="epoch",
        speech_id="response:reply",
        played_audio_end_us=500_000,
        confirmed_text_end=0,
        observed_at_ns=10,
        position_precision="sample",
        played_position_samples=500,
        sample_rate_hz=1000,
    )
    ledger.observe_playback_fact("reply", context(), fact)
    assert not ledger.observe_playback_fact(
        "reply",
        context(),
        replace(
            fact,
            observed_at_ns=11,
            played_position_samples=1200,
            sample_rate_hz=2000,
            played_audio_end_us=600_000,
        ),
    )
    assert ledger.reply.playback == fact


@pytest.mark.parametrize("replacement_rate,accepted", [(1000, True), (2000, False)])
def test_legacy_downgrade_preserves_the_bound_sample_rate(replacement_rate, accepted):
    from dataclasses import replace

    from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
    from server.realtime.protocol.playback import ReplyPlayback
    from tests.realtime.test_reply_revision_controller import commit

    ledger = ReplyRevisionController()
    commit(ledger, ctx=context())
    ledger.bind_response("reply", context())
    fact = ReplyPlayback(
        output_epoch="epoch",
        speech_id="response:reply",
        played_audio_end_us=500_000,
        confirmed_text_end=0,
        observed_at_ns=10,
        position_precision="sample",
        played_position_samples=500,
        sample_rate_hz=1000,
    )
    ledger.observe_playback_fact("reply", context(), fact)
    unknown = replace(
        fact,
        position_precision="unknown",
        played_position_samples=None,
        sample_rate_hz=None,
        observed_at_ns=11,
    )
    ledger.observe_playback_fact("reply", context(), unknown)
    assert (
        ledger.observe_playback_fact(
            "reply",
            context(),
            replace(
                fact,
                observed_at_ns=12,
                played_position_samples=replacement_rate * 6 // 10,
                sample_rate_hz=replacement_rate,
                played_audio_end_us=600_000,
            ),
        )
        is accepted
    )
    if accepted:
        assert ledger.reply.playback.sample_rate_hz == replacement_rate
    else:
        # The unchanged-position downgrade keeps the original position age.
        assert ledger.reply.playback.position_precision == "unknown"
        assert ledger.reply.playback.sample_rate_hz is None


async def test_epoch_command_without_pcm_metadata_cannot_supply_a_current_sentence():
    from dataclasses import replace

    from server.realtime import ReportPlaybackProgress

    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        before = core._input_pipeline.response_revision("reply").playback
        span = before.current_sentence
        await core.send(
            ReportPlaybackProgress(
                command_id="legacy-precise",
                idempotency_key="legacy-precise",
                context=replace(context(), response_id="reply"),
                speech_id="response:reply",
                played_audio_end_us=500_000,
                delivered_text_end=0,
                output_epoch="epoch",
                observed_at_ns=before.observed_at_ns + 1,
                current_sentence=span,
            )
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert fact.position_precision == "unknown" and fact.current_sentence is None
        assert fact.played_position_samples is None and fact.sample_rate_hz is None
    finally:
        await core.close()


async def test_partial_finished_regression_is_not_an_actual_response_terminal():
    core, bridge = await playing_core()
    try:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=500,
            )
        )
        before = core._input_pipeline.response_revision("reply").playback
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="finished",
                played_position_samples=400,
            )
        )
        assert core._input_pipeline.response_revision("reply").playback == before
        assert not before.terminal
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="response:reply",
                generation=1,
                phase="playing",
                played_position_samples=600,
            )
        )
        fact = core._input_pipeline.response_revision("reply").playback
        assert not fact.terminal and fact.played_position_samples == 600
        assert fact.current_sentence is not None
    finally:
        await core.close()


def test_sample_precision_cannot_be_declared_without_an_actual_pcm_clock():
    from server.realtime.protocol.playback import ReplyPlayback

    with pytest.raises(ValueError, match="actual PCM"):
        ReplyPlayback(
            output_epoch="epoch",
            speech_id="response:reply",
            played_audio_end_us=500_000,
            confirmed_text_end=0,
            observed_at_ns=10,
            position_precision="sample",
        )
