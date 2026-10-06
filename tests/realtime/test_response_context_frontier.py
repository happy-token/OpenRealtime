"""Real playback receipts refine Journal projections before Brain admission.

Providers and renderer positions are controlled; this is not physical audio E2E.
"""

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.realtime import AppendItem, RequestResponse
from server.realtime.errors import ContextVisibilityError
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.voice_session.context import FullConversationContextProjector, digest_source_items
from server.voice_session.protocol import PlaybackProgressV2
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_realtime_websocket_bridge import context
from tests.realtime.test_reply_playback_observation import playing_core


class RecordingBrain:
    def __init__(self):
        self.turns = []

    async def stream(self, turn):
        self.turns.append(turn)
        yield "第一句。第二句。"


class GatedProjector(FullConversationContextProjector):
    def __init__(self, *, blocked):
        self.calls = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.blocked = blocked

    async def project_text(self, items):
        self.calls.append(items)
        if len(self.calls) == 1 and self.blocked:
            self.entered.set()
            await self.release.wait()
        return await super().project_text(items)


async def position(bridge, samples):
    await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id="response:reply",
        generation=1, phase="playing", played_position_samples=samples))


async def next_input(core, conversation):
    await wait_for(lambda: any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                              for item in core._projected_items.values()))
    ctx = replace(context(), turn_id="next", generation=2)
    await conversation.send(AppendItem(command_id="next", idempotency_key="next", context=ctx,
        draft=ConversationItemDraft(item_id="next", context=ctx,
            kind=ConversationItemKind.USER_INPUT, status=ConversationItemStatus.COMPLETED,
            producer="test", content=(TextContent("接着说"),))))
    return RequestResponse(command_id="next-response", idempotency_key="next-response",
        context=ctx, response_id="next-response", minimum_thread_sequence=core._last_projected_thread_sequence)


@pytest.mark.parametrize("stage,samples,projection_calls", [
    ("projecting", 2000, 2), ("preparing", 2000, 2), ("projecting", 1500, 1),
])
async def test_brain_admission_rebuilds_changed_heard_history_but_not_sample_only_progress(
    monkeypatch, stage, samples, projection_calls,
):
    brain, store = RecordingBrain(), InMemorySpeechDeliveryStore()
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=store)
    conversation = bridge._conversation
    projector = GatedProjector(blocked=stage == "projecting")
    preparing, release_preparing = asyncio.Event(), asyncio.Event()
    task = None
    try:
        await position(bridge, 1000)
        command = await next_input(core, conversation)
        immutable_digests = {item.item_id: item.item_digest for item in core._projected_items.values()}
        core._context_projector = projector
        original = core._input_pipeline.response_started

        async def gated_preparing(*args, **kwargs):
            preparing.set()
            await release_preparing.wait()
            await original(*args, **kwargs)

        if stage == "preparing":
            monkeypatch.setattr(core._input_pipeline, "response_started", gated_preparing)
        # Submit at the Core seam so the test can interleave a transport receipt
        # while preparation is suspended; the actual Managed event pump stays live.
        task = asyncio.create_task(core.send(command))
        await asyncio.wait_for((preparing if stage == "preparing" else projector.entered).wait(), 1)
        assert len(brain.turns) == 1
        await position(bridge, samples)
        assert all(core._projected_items[item.sequence].item_digest == immutable_digests[item.item_id]
                   for item in projector.calls[0])
        projector.release.set()
        release_preparing.set()
        await asyncio.wait_for(task, 1)
        await wait_for(lambda: len(brain.turns) == 2)
        assert "第一句。" in brain.turns[-1].conversation_context
        assert ("第二句。" in brain.turns[-1].conversation_context) is (samples == 2000)
        assert len(projector.calls) == projection_calls
        assert brain.turns[-1].context_projection_digest == digest_source_items(projector.calls[-1])
    finally:
        projector.release.set()
        release_preparing.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await conversation.close()


async def test_continuously_changed_projection_fails_with_bounded_attempts_before_brain():
    brain, store = RecordingBrain(), InMemorySpeechDeliveryStore()
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=store)
    conversation = bridge._conversation
    calls = []
    try:
        command = await next_input(core, conversation)
        source_sequence = command.minimum_thread_sequence

        class MovingProjector(FullConversationContextProjector):
            async def project_text(self, items):
                calls.append(items)
                # Fault injection: a concurrent owner changes the selected input
                # on every asynchronous projection completion.
                current = core._projected_items[source_sequence]
                core._projected_items[source_sequence] = replace(current,
                    content=(TextContent(f"接着说{len(calls)}"),))
                return await super().project_text(items)

        core._context_projector = MovingProjector()
        with pytest.raises(ContextVisibilityError, match="retry budget exhausted"):
            await asyncio.wait_for(core.send(command), 1)
        assert len(calls) == 3
        assert len(brain.turns) == 1
        assert core._active_response_id is None
        assert core._response_task is None or core._response_task.done()
    finally:
        await conversation.close()
