"""An external speech lease is distinct from its source response identity."""

from dataclasses import replace

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.realtime import (
    AppendSpeechText,
    CommitSpeech,
    RequestResponse,
    SpeechAudioCompleted,
    StartSpeech,
)
from server.realtime.journaled import JournaledRealtimeConversation
from server.realtime.protocol.engine import is_output_context_current
from server.realtime.transport.websocket import RealtimeWebSocketFrameBridge
from server.transport.frames import AssistantAudioChunkFrame
from tests.realtime.test_reply_playback_observation import Provider
from tests.realtime.test_reply_revision_production_delivery import (
    Transport,
    append_user,
    context,
    open_core,
)


@pytest.mark.parametrize("source_response", [None, "parent", "revoked-parent"])
@pytest.mark.parametrize("revoke_external", [False, True])
async def test_external_terminal_uses_live_speech_lease_not_source_response(source_response, revoke_external):
    core = await open_core(tts=Provider())
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(), engine_conversation=core)
    transport = Transport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport)
    ctx = replace(context(), response_id=source_response)
    try:
        await append_user(conversation)
        await conversation.send(StartSpeech(command_id="start", idempotency_key="start", context=ctx, speech_id="external"))
        await conversation.send(AppendSpeechText(command_id="text", idempotency_key="text", context=ctx,
            speech_id="external", text_sequence=1, delta="第一句。第二句。"))
        await conversation.send(CommitSpeech(command_id="commit", idempotency_key="commit", context=ctx, speech_id="external"))
        async for event in conversation.events():
            if isinstance(event, SpeechAudioCompleted):
                completed = event
                break
            await bridge.handle_event(event)
        assert any(isinstance(frame, AssistantAudioChunkFrame) and not frame.is_final for frame in transport.frames)
        if source_response == "revoked-parent" or revoke_external:
            response_id = "external" if revoke_external else source_response
            await core._revoke_brain_output(RequestResponse(command_id="revoke", idempotency_key="revoke", context=replace(ctx, response_id=response_id),
                response_id=response_id, minimum_thread_sequence=1))
        assert completed.context.response_id == source_response
        assert is_output_context_current(conversation, completed) is (not revoke_external)
        await bridge.handle_event(completed)
        terminals = [frame for frame in transport.frames if isinstance(frame, AssistantAudioChunkFrame) and frame.is_final]
        assert len(terminals) == (0 if revoke_external else 1)
    finally:
        await conversation.close()
