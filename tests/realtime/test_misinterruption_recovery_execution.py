"""Original durable user input -> actual stopped playback -> fresh continuation."""

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
)
from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.realtime import ResponseStarted
from server.realtime.capabilities.asr import CommitAsrInput
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.runtime import RealtimeRuntimeFactory
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.speech.plugins.doubao_tts_direct import _alignment_chunks
from server.speech.tts import SynthesizedAudioChunk
from server.transport.frames import (
    AssistantAudioChunkFrame,
    AssistantSpeechCancelledFrame,
    UserTextFrame,
)
from server.turn_policy.policy import TurnPolicy
from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
from tests.realtime.test_automatic_context_repair import RepairBrain
from tests.realtime.test_coordinated_turn_manager import Endpoint, Interrupt, start, stop, text
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_realtime_websocket_bridge import RecordingTransport, context
from tests.realtime.test_reply_revision_coordination import final
from tests.realtime.test_reply_revision_production_delivery import open_core


class RecoveryTts:
    async def synthesize_stream(self, value):
        sentences = [part + "。" for part in value.split("。") if part]
        yield SynthesizedAudioChunk(pcm16=b"\0\0" * (1000 * len(sentences)), sample_rate_hz=1000, is_final=False)
        for index, sentence in enumerate(sentences):
            for chunk in _alignment_chunks({"text": sentence, "words": [{
                "word": sentence, "startTime": index, "endTime": index + 1,
            }]}, 1000):
                yield chunk


@pytest.mark.parametrize("endpoint_session", [False, True])
@pytest.mark.parametrize("facts_first", [False, True])
@pytest.mark.parametrize("followup", ["none", "replay", "next_input", "new_vad", "stale_vad", "recover_again", "unknown_stop", "stale_stop", "missing_receipt"])
async def test_actual_pipeline_recovers_original_input_under_new_reply_and_output_epoch(monkeypatch, facts_first, followup, endpoint_session):
    brain = RepairBrain(generation_finished=True)
    journal, store = InMemoryConversationJournal(), InMemorySpeechDeliveryStore()
    core = await open_core(brain=brain, tts=RecoveryTts(), speech_deliveries=store, interaction_context=context(),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=Endpoint(),
            semantic_interruption_classifier=Interrupt(), input_evidence_journal=journal))
    actor = core._input_pipeline._turn_manager
    original_asr = core._input_pipeline._asr.send
    new_speech_seen = asyncio.Event()
    original_started = core._input_pipeline.response_started

    async def raced_started(response_id, **kwargs):
        await original_started(response_id, **kwargs)
        repair = kwargs.get("repair")
        if followup in {"new_vad", "stale_vad"} and kwargs.get("preparing") and repair is not None and repair.recovery is not None:
            await start(actor, replace(context(), turn_id="new-vad" if followup == "new_vad" else "overlap",
                generation=4 if followup == "new_vad" else 2))
            new_speech_seen.set()

    monkeypatch.setattr(core._input_pipeline, "response_started", raced_started)

    async def controlled_asr(command):
        if not isinstance(command, CommitAsrInput):
            await original_asr(command)

    monkeypatch.setattr(core._input_pipeline._asr, "send", controlled_asr)

    class Engine:
        async def open(self, **kwargs):
            return core

    conversation = await RealtimeRuntimeFactory(engine=Engine(), journal=journal,
        speech_deliveries=store, active_conversations=ActiveRealtimeConversations()).open(context=context(), profile=None)
    transport = RecordingTransport()
    endpoint = InMemoryEndpointSession("recovery-test", transport, transport.receive(), buffer_outbound_frames=False) if endpoint_session else transport
    epoch = endpoint.output_epoch if endpoint_session else "epoch"
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation,
        transport=endpoint, output_epoch=epoch, precise_output_stop=True,
        output_stop_timeout_ms=50 if followup == "missing_receipt" else 1500)

    started_events = []

    async def pump():
        async for event in conversation.events():
            if isinstance(event, ResponseStarted):
                started_events.append(event)
            await bridge.handle_event(event)

    pumping = asyncio.create_task(pump())
    try:
        await start(actor, context())
        await text(actor, "说两句", ctx=context())
        await stop(actor, context())
        await wait_for(lambda: actor.snapshot().commit_pending)
        await final(actor, context(), "说两句")
        await wait_for(lambda: len(brain.turns) == 1 and core._response_task is None)
        previous = actor._revisions.reply
        speech = f"response:{previous.response_id}"
        await wait_for(lambda: speech in bridge._playback_by_speech and bridge._playback_by_speech[speech].generation_complete)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch=epoch, speech_id=speech,
            generation=1, phase="playing", played_position_samples=500))
        overlap = replace(context(), turn_id="overlap", generation=2)
        await start(actor, overlap)
        await text(actor, "等一下换个问题", ctx=overlap)
        await wait_for(lambda: any(isinstance(frame, AssistantSpeechCancelledFrame)
            and frame.speech_id == speech for frame in transport.frames))
        request = next(frame for frame in transport.frames if isinstance(frame, AssistantSpeechCancelledFrame) and frame.speech_id == speech)
        await wait_for(lambda: actor._input.yielded)

        async def stopped():
            if followup == "missing_receipt":
                return
            outcome = "unknown" if followup == "unknown_stop" else "stale" if followup == "stale_stop" else "queue_stopped"
            await bridge.handle_inbound(OutputStopResult(output_epoch=epoch, speech_id=speech, generation=1,
                stop_command_id=request.stop_command_id, outcome=outcome,
                played_position_samples=2000 if outcome == "queue_stopped" else None))

        if facts_first:
            await stopped()
        await text(actor, "好的", revision=2, ctx=overlap)
        await stop(actor, overlap)
        await wait_for(lambda: actor._input is None)
        if not facts_first:
            assert len(brain.turns) == 1, "no continuation before actual physical stop and projection"
            await stopped()
        if followup in {"unknown_stop", "stale_stop", "missing_receipt"}:
            await wait_for(lambda: bridge._output_failure.is_set() and actor._revisions.output_stop is not None
                and actor._revisions.output_stop.state == "STOP_UNKNOWN")
            fact = actor._revisions.output_stop
            assert fact.stop_command_id == request.stop_command_id
            assert len(brain.turns) == 1 and not actor.response_delivery_allowed(previous.response_id)
            assert not any(frame.type == "output_epoch_started" for frame in transport.frames)
            # A late confirmation cannot turn the immutable failed operation
            # into recovery permission, even with fresh reliable feedback.
            await bridge.handle_inbound(OutputStopResult(output_epoch=epoch, speech_id=speech, generation=1,
                stop_command_id=request.stop_command_id, outcome="queue_stopped", played_position_samples=2000))
            await asyncio.sleep(0)
            assert actor._revisions.output_stop == fact
            assert len(brain.turns) == 1 and bridge._stop_output_failed
            return
        if followup == "new_vad":
            await wait_for(lambda: new_speech_seen.is_set() and core._response_task is None)
            assert len(brain.turns) == 1
            assert actor._input is not None and actor._input.speech_active
            assert not actor.response_delivery_allowed(actor._revisions.reply.response_id)
            assert not any(frame.type == "output_epoch_started" for frame in transport.frames)
            return
        await wait_for(lambda: len(brain.turns) == 2 and core._response_task is None)
        current = actor._revisions.reply
        assert (current.input_id, current.input_version) == (previous.input_id, previous.input_version)
        assert current.supersedes_response_id == previous.response_id and current.reply_version == previous.reply_version + 1
        assert current.generation == 3 and brain.turns[-1].generation == 3
        assert brain.turns[-1].text == "说两句" and brain.turns[-1].context_repair
        assert "第一句。" in brain.turns[-1].conversation_context
        assert "不得再次请求任何工具或委派" in brain.turns[-1].model_text
        rows = await journal.read(JournalScope.from_context(context()))
        assert sum(row.kind is ConversationItemKind.USER_INPUT for row in rows) == 1
        await wait_for(lambda: any(isinstance(frame, AssistantAudioChunkFrame) and frame.generation == 3 for frame in transport.frames))
        rotations = [frame for frame in transport.frames if frame.type == "output_epoch_started"]
        assert len(rotations) == 1 and rotations[0].previous_output_epoch == epoch
        assert bridge.output_epoch == rotations[0].output_epoch != epoch
        audio = next(frame for frame in transport.frames if isinstance(frame, AssistantAudioChunkFrame) and frame.generation == 3)
        assert transport.frames.index(rotations[0]) < transport.frames.index(audio)
        assert not actor.response_delivery_allowed(previous.response_id)
        await wait_for(lambda: any(frame.type == "assistant_response_completed" and frame.generation == 3
            for frame in transport.frames))
        archived = ReplyRevisionController()
        for row in await journal.read(JournalScope.from_context(context())):
            archived.restore_item(row)
        assert archived.reply.response_id == current.response_id
        assert archived.reply.input_context.generation == 1
        assert archived.reply.generation == 3 and archived.reply.reply_version == 2
        assert not archived.delivery_allowed(current.response_id)
        if followup == "replay":
            before = len(transport.frames)
            await bridge.handle_event(next(event for event in started_events if event.recovery is not None))
            await asyncio.sleep(0)
            assert not bridge._output_failure.is_set()
            assert len(transport.frames) == before
        elif followup == "recover_again":
            recovered_speech = f"response:{current.response_id}"
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch=bridge.output_epoch,
                speech_id=recovered_speech, generation=3, phase="playing", played_position_samples=500))
            new_overlap = replace(context(), turn_id="second-overlap", generation=4)
            await start(actor, new_overlap)
            await text(actor, "等一下换个问题", ctx=new_overlap)
            await wait_for(lambda: any(isinstance(frame, AssistantSpeechCancelledFrame)
                and frame.speech_id == recovered_speech for frame in transport.frames))
            new_stop = next(frame for frame in transport.frames if isinstance(frame, AssistantSpeechCancelledFrame)
                and frame.speech_id == recovered_speech)
            await wait_for(lambda: actor._input.yielded)
            # Late evidence from the retired epoch cannot settle this new stop.
            await stopped()
            assert bridge._output_stops[new_stop.stop_command_id].state == "STOP_REQUESTED"
            await text(actor, "好的", revision=2, ctx=new_overlap)
            await stop(actor, new_overlap)
            await wait_for(lambda: actor._input is None)
            await bridge.handle_inbound(OutputStopResult(output_epoch=bridge.output_epoch,
                speech_id=recovered_speech, generation=3, stop_command_id=new_stop.stop_command_id,
                outcome="queue_stopped", played_position_samples=1000))
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            latest = actor._revisions.reply
            assert latest.generation == 5 and latest.reply_version == 3
            assert (latest.input_id, latest.input_version) == (previous.input_id, previous.input_version)
            assert latest.input_context.generation == 1
            assert latest.supersedes_response_id == current.response_id
            assert brain.turns[-1].text == "说两句" and brain.turns[-1].context_repair
            await wait_for(lambda: len([frame for frame in transport.frames if frame.type == "output_epoch_started"]) == 2)
            assert bridge._generation == 6
            rows = await journal.read(JournalScope.from_context(context()))
            assert sum(row.kind is ConversationItemKind.USER_INPUT for row in rows) == 1
        elif followup == "next_input":
            playback = bridge._playback_by_speech[f"response:{current.response_id}"]
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch=bridge.output_epoch,
                speech_id=playback.speech_id, generation=3, phase="finished",
                played_position_samples=playback.audio_samples))
            await bridge.handle_inbound(UserTextFrame(text="下一个问题"))
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            assert brain.turns[-1].generation == 4
            assert brain.turns[-1].text == "下一个问题"
            assert not brain.turns[-1].context_repair
            rows = await journal.read(JournalScope.from_context(context()))
            users = [row for row in rows if row.kind is ConversationItemKind.USER_INPUT]
            assert len(users) == 2 and users[-1].context.generation == 4
    finally:
        pumping.cancel()
        await asyncio.gather(pumping, return_exceptions=True)
        await bridge.close()
        await conversation.close()
