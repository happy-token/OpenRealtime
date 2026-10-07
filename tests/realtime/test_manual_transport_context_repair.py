"""Actual UserTextFrame route, projection waiter, model reply and stop receipt."""

import asyncio

import pytest

from server.conversation_journal import ConversationItemKind, JournalScope, TextContent
from server.conversation_journal.input_evidence import read_input_evidence
from server.transport.frames import (
    AssistantResponseCompletedFrame,
    AssistantSpeechCancelledFrame,
    UserTextFrame,
)
from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
from tests.realtime.test_automatic_context_repair import automatic_reply
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_realtime_websocket_bridge import context


@pytest.mark.parametrize("precise_stop", [False, True])
async def test_user_text_transport_reply_repairs_only_after_actual_stop(monkeypatch, precise_stop):
    async with automatic_reply(monkeypatch, precise_stop=precise_stop, evidence=True) as (core, conversation, bridge, brain, journal, previous, first, _):
        async def pump():
            async for event in conversation.events():
                await bridge.handle_event(event)

        pumping = asyncio.create_task(pump())
        try:
            if precise_stop:
                await wait_for(lambda: any(isinstance(frame, AssistantSpeechCancelledFrame)
                    and frame.speech_id == f"response:{first}" for frame in bridge._transport.frames))
                initial_stop = next(frame for frame in bridge._transport.frames
                    if isinstance(frame, AssistantSpeechCancelledFrame) and frame.speech_id == f"response:{first}")
                await bridge.handle_inbound(OutputStopResult(output_epoch=initial_stop.output_epoch,
                    speech_id=initial_stop.speech_id, generation=initial_stop.generation,
                    stop_command_id=initial_stop.stop_command_id, outcome="queue_stopped", played_position_samples=500))
            await wait_for(lambda: bridge._generation == 3 and any(isinstance(frame, AssistantResponseCompletedFrame)
                and frame.generation == 2 for frame in bridge._transport.frames))
            await asyncio.wait_for(bridge.handle_inbound(UserTextFrame(text="  改成查看明天的天气  ")), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            original = core._input_pipeline._turn_manager._revisions.reply
            speech = f"response:{original.response_id}"
            await wait_for(lambda: speech in bridge._playback_by_speech and bridge._playback_by_speech[speech].generation_complete)
            rows = await journal.read(JournalScope.from_context(context()))
            manual = next(item for item in rows if item.kind is ConversationItemKind.USER_INPUT
                and item.producer == "realtime-websocket-transport")
            assert manual.content == (TextContent("改成查看明天的天气"),)
            assert original.input_id == manual.item_id and original.input_version == 1
            assert (original.turn_id, original.generation) == (manual.context.turn_id, 3)
            assert brain.turns[-1].text == "改成查看明天的天气"
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{previous.response_id}",
                generation=2, phase="finished", played_position_samples=2000))
            await wait_for(lambda: core._response_task is None and core._published_brain_output.playback_stop_pending)
            assert len(brain.turns) == 3
            if precise_stop:
                await wait_for(lambda: any(isinstance(frame, AssistantSpeechCancelledFrame) and frame.speech_id == speech
                    for frame in bridge._transport.frames))
                request = next(frame for frame in bridge._transport.frames
                    if isinstance(frame, AssistantSpeechCancelledFrame) and frame.speech_id == speech)
                actor = core._input_pipeline._turn_manager
                await wait_for(lambda: actor._revisions.output_stop is not None
                    and actor._revisions.output_stop.stop_command_id == request.stop_command_id)
                assert actor._revisions.output_stop.state == "STOP_REQUESTED"
                assert not original.delivery_permitted or not actor._revisions.reply.delivery_permitted
                await bridge.handle_inbound(OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
                    generation=request.generation, stop_command_id=request.stop_command_id,
                    outcome="queue_stopped", played_position_samples=2000))
            else:
                await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=speech,
                    generation=3, phase="stopped", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
            current = core._input_pipeline._turn_manager._revisions.reply
            assert current.input_id == original.input_id and current.input_version == original.input_version
            assert current.supersedes_response_id == original.response_id
            assert current.reply_version == original.reply_version + 1
            assert brain.turns[-1].text == "改成查看明天的天气" and brain.turns[-1].context_repair
            if precise_stop:
                await wait_for(lambda: actor._evidence._pending == 0)
                evidence = await read_input_evidence(journal, context())
                facts = [row["detail"] for row in evidence["records"]
                    if row["detail"]["event"] == "reply_output_stop_observed"
                    and row["detail"]["stop_command_id"] == request.stop_command_id]
                assert [row["state"] for row in facts] == ["STOP_REQUESTED", "STOP_CONFIRMED"]
                assert all(row["input_id"] == original.input_id and row["reply_version"] == original.reply_version for row in facts)
                assert facts[0]["operation_sequence"] == facts[1]["operation_sequence"] == 2
                assert actor._revisions.output_stop is None
        finally:
            pumping.cancel()
            await asyncio.gather(pumping, return_exceptions=True)
            await bridge.close()
