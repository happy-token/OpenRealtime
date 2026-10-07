"""Explicit requests and model deliveries share the actual reply repair path."""

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    JournalScope,
    TextContent,
)
from server.realtime import (
    AppendItem,
    DeliverItem,
    ItemDeliveryStarted,
    RequestResponse,
    ResponseStarted,
)
from server.realtime.errors import ContextVisibilityError
from server.realtime.protocol.commands import DeliveryMode
from server.voice_session.protocol import PlaybackProgressV2
from tests.realtime.test_automatic_context_repair import automatic_reply
from tests.realtime.test_coordinated_turn_manager import start, text
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_realtime_websocket_bridge import context


@pytest.mark.parametrize("origin", ["request", "typed", "delivery_user", "delivery_tool", "typed_tool"])
async def test_explicit_model_reply_gets_a_new_version_after_late_heard_context(monkeypatch, origin):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, journal, _previous, first, _):
        old = core._published_brain_output.command
        ctx = (replace(context(), turn_id="typed", generation=3) if origin in {"typed", "typed_tool"}
               else replace(old.context, response_id=None))
        source = next(item for item in core._projected_items.values()
                      if item.sequence == old.minimum_thread_sequence)
        if origin == "typed_tool":
            await conversation.send(AppendItem(command_id="manual-source", idempotency_key="manual-source", context=ctx,
                draft=ConversationItemDraft(item_id="manual-source", context=ctx, kind=ConversationItemKind.USER_INPUT,
                    status=ConversationItemStatus.COMPLETED, producer="realtime-websocket-transport",
                    content=(TextContent("用文字继续"),))))
        if origin in {"typed", "delivery_tool", "typed_tool"}:
            source_ctx = replace(ctx, response_id=old.response_id, call_id="finished-call") if origin in {"delivery_tool", "typed_tool"} else ctx
            await conversation.send(AppendItem(command_id="explicit-source", idempotency_key="explicit-source", context=source_ctx,
                draft=ConversationItemDraft(item_id="explicit-source", context=source_ctx,
                    kind=ConversationItemKind.USER_INPUT if origin == "typed" else ConversationItemKind.TOOL_RESULT,
                    status=ConversationItemStatus.COMPLETED, producer="realtime-websocket-transport" if origin == "typed" else "test-tool",
                    content=(TextContent("用文字继续" if origin == "typed" else "订单已创建：ORDER-123"),))))
            await wait_for(lambda: "explicit-source" in core._projected_sequence_by_item_id)
            source = core._item_by_id("explicit-source")
        response_id = "delivery:explicit" if origin.startswith("delivery") or origin == "typed_tool" else "explicit"
        if origin.startswith("delivery") or origin == "typed_tool":
            await conversation.send(DeliverItem(command_id="explicit", idempotency_key="explicit", context=ctx,
                delivery_id="explicit", item_id=source.item_id))
        else:
            await conversation.send(RequestResponse(command_id="explicit", idempotency_key="explicit", context=ctx,
                response_id=response_id, minimum_thread_sequence=source.sequence))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        original = core._input_pipeline.response_revision(response_id)
        assert original.input_id is not None, "explicit user input must have a repairable input identity"
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
        current = core._input_pipeline._turn_manager._revisions.reply
        assert current.response_id != response_id
        assert current.supersedes_response_id == response_id
        assert (current.input_id, current.input_version) == (original.input_id, original.input_version)
        assert current.reply_version == original.reply_version + 1
        assert brain.turns[-1].context_repair
        assert brain.turns[-1].text == ("用文字继续" if origin in {"typed", "typed_tool"} else "请继续")
        assert "第二句。" in brain.turns[-1].conversation_context
        if origin in {"delivery_tool", "typed_tool"}:
            assert "订单已创建：ORDER-123" in brain.turns[-1].conversation_context
        await wait_for(lambda: any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
            and item.context.response_id == current.response_id for item in core._projected_items.values()))
        rows = await journal.read(JournalScope.from_context(context()))
        repaired = next(item for item in rows if item.context.response_id == current.response_id
                        and item.kind is ConversationItemKind.ASSISTANT_OUTPUT)
        assert repaired.parent_item_id == source.item_id
        assert repaired.provider_metadata["supersedes_response_id"] == response_id
        assert sum(item.kind is ConversationItemKind.USER_INPUT for item in rows) == (3 if origin in {"typed", "typed_tool"} else 2)


async def test_durable_manual_input_blocks_old_repair_before_response_request(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        ctx = replace(context(), turn_id="typed", generation=3)
        await conversation.send(AppendItem(command_id="manual", idempotency_key="manual", context=ctx,
            draft=ConversationItemDraft(item_id="manual", context=ctx, kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED, producer="realtime-websocket-transport",
                content=(TextContent("新的重要问题"),))))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: core._response_task is None and not core._detached_response_tasks)
        assert len(brain.turns) == 2, "a committed manual input must fence old automatic repair"
        assert core._item_by_id("manual").content == (TextContent("新的重要问题"),)


async def test_rejected_explicit_request_keeps_the_previous_repair_owner(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, previous, first, _):
        old = core._published_brain_output.command
        with pytest.raises(ValueError, match="response identity"):
            await conversation.send(replace(old, command_id="rejected", idempotency_key="rejected"))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == previous.response_id


async def test_new_manual_commit_retires_pending_asr_and_preserves_its_evidence(monkeypatch):
    from server.conversation_journal.input_evidence import read_input_evidence
    async with automatic_reply(monkeypatch, evidence=True) as (core, conversation, _bridge, brain, journal, _previous, _first, _):
        actor = core._input_pipeline._turn_manager
        pending_ctx = replace(context(), turn_id="pending-audio", generation=3)
        await start(actor, pending_ctx)
        await text(actor, "还有一个尚未说完的补充", ctx=pending_ctx)
        pending_id = actor._input.identity
        ctx = replace(context(), turn_id="manual", generation=4)
        await conversation.send(AppendItem(command_id="manual", idempotency_key="manual", context=ctx,
            draft=ConversationItemDraft(item_id="manual", context=ctx, kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED, producer="realtime-websocket-transport",
                content=(TextContent("改用文字提问"),))))
        await conversation.send(RequestResponse(command_id="manual-reply", idempotency_key="manual-reply", context=ctx,
            response_id="manual-reply", minimum_thread_sequence=core._projected_sequence_by_item_id["manual"]))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None and actor._evidence._pending == 0)
        assert actor._input is None and actor._failure is None
        assert actor._revisions.input.input_id == "manual"
        evidence = await read_input_evidence(journal, context())
        superseded = next(record["detail"] for record in evidence["records"]
                          if record["detail"]["event"] == "manual_input_superseded")
        assert superseded["input_id"] == pending_id
        assert superseded["text"] == "还有一个尚未说完的补充"
        assert superseded["replacement_item_id"] == "manual"


async def test_starting_an_asr_backed_reply_keeps_a_subsequent_voice_supplement(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, _bridge, brain, _journal, _previous, _first, _):
        actor = core._input_pipeline._turn_manager
        pending_ctx = replace(context(), turn_id="supplement", generation=3)
        await start(actor, pending_ctx)
        await text(actor, "还有后面的内容", ctx=pending_ctx)
        pending = actor._input
        old = core._published_brain_output.command
        await conversation.send(replace(old, response_id="explicit", context=replace(old.context, response_id="explicit"),
            command_id="explicit", idempotency_key="explicit", output_item_id=None))
        await wait_for(lambda: len(brain.turns) == 3)
        assert actor._input is pending and pending.text == "还有后面的内容"
        assert actor._failure is None


def repair_controller(conversation):
    from server.realtime.control_plane import RealtimeTurnController
    while not isinstance(conversation, RealtimeTurnController):
        conversation = conversation._conversation
    return conversation


async def append_manual(conversation, *, generation=3):
    ctx = replace(context(), turn_id="manual", generation=generation)
    await conversation.send(AppendItem(command_id="manual", idempotency_key="manual", context=ctx,
        draft=ConversationItemDraft(item_id="manual", context=ctx, kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED, producer="realtime-websocket-transport",
            content=(TextContent("新的重要问题"),))))
    return ctx


@pytest.mark.parametrize("replay", [False, True])
async def test_late_delivery_started_cannot_restore_owner_after_new_durable_input(monkeypatch, replay):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        controller = repair_controller(conversation)
        blocked, release = asyncio.Event(), asyncio.Event()
        handle = controller._handle_event

        async def gated(event):
            if isinstance(event, ItemDeliveryStarted) and event.delivery_id == "older":
                blocked.set()
                await release.wait()
            await handle(event)

        monkeypatch.setattr(controller, "_handle_event", gated)
        old = core._published_brain_output.command
        source = core._projected_items[old.minimum_thread_sequence]
        try:
            delivery = DeliverItem(command_id="older", idempotency_key="older",
                context=replace(old.context, response_id=None), delivery_id="older", item_id=source.item_id)
            await conversation.send(delivery)
            await asyncio.wait_for(blocked.wait(), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            await append_manual(conversation)
            if replay:
                await conversation.send(delivery)
                assert len(brain.turns) == 3
            release.set()
            await wait_for(lambda: "delivery:older" not in controller._response_drafts
                and any(item.context.response_id == "delivery:older" for item in core._projected_items.values()))
            assert controller._repairable_request is None
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: not core._input_pipeline._turn_manager._revisions.reply.delivery_permitted)
            assert len(brain.turns) == 3
        finally:
            release.set()


async def test_late_response_started_cannot_clear_a_newer_request_owner(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        controller = repair_controller(conversation)
        blocked, release = asyncio.Event(), asyncio.Event()
        handle = controller._handle_event

        async def gated(event):
            if isinstance(event, ResponseStarted) and event.response_id == "older":
                blocked.set()
                await release.wait()
            await handle(event)

        monkeypatch.setattr(controller, "_handle_event", gated)
        old = core._published_brain_output.command
        try:
            await conversation.send(replace(old, command_id="older", idempotency_key="older", response_id="older",
                context=replace(old.context, response_id="older"), output_item_id=None))
            await asyncio.wait_for(blocked.wait(), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            ctx = await append_manual(conversation)
            await conversation.send(RequestResponse(command_id="newer", idempotency_key="newer", context=ctx,
                response_id="newer", minimum_thread_sequence=core._projected_sequence_by_item_id["manual"]))
            await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
            release.set()
            await wait_for(lambda: any(item.context.response_id == "newer" for item in core._projected_items.values()))
            assert controller._repairable_request.response_id == "newer"
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 5 and core._response_task is None)
            assert brain.turns[-1].text == "新的重要问题"
            assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "newer"
        finally:
            release.set()


async def test_cancelled_admission_restores_the_previous_repair_owner(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, previous, first, _):
        blocked = asyncio.Event()
        project = core._turn_from_projection

        async def gated(*args, **kwargs):
            blocked.set()
            await asyncio.Event().wait()
            return await project(*args, **kwargs)

        monkeypatch.setattr(core, "_turn_from_projection", gated)
        old = core._published_brain_output.command
        task = asyncio.create_task(conversation.send(replace(old, command_id="aborted", idempotency_key="aborted",
            response_id="aborted", context=replace(old.context, response_id="aborted"), output_item_id=None)))
        try:
            await asyncio.wait_for(blocked.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert repair_controller(conversation)._repairable_request.response_id == previous.response_id
            monkeypatch.setattr(core, "_turn_from_projection", project)
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == previous.response_id
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_legal_queued_model_deliveries_keep_the_last_started_repair_owner(monkeypatch):
    async with automatic_reply(monkeypatch, generation_finished=False) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        old = core._published_brain_output.command
        source = core._projected_items[old.minimum_thread_sequence]
        for name in ("queued-a", "queued-b"):
            await conversation.send(DeliverItem(command_id=name, idempotency_key=name,
                context=replace(old.context, response_id=None), delivery_id=name, item_id=source.item_id))
        brain.release.set()
        await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
        await wait_for(lambda: any(item.context.response_id == "delivery:queued-b" for item in core._projected_items.values()))
        assert repair_controller(conversation)._repairable_request.response_id == "delivery:queued-b"
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 5 and core._response_task is None)
        assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "delivery:queued-b"


async def test_rejected_request_does_not_revoke_an_already_queued_model_delivery(monkeypatch):
    async with automatic_reply(monkeypatch, generation_finished=False) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        old = core._published_brain_output.command
        source = core._projected_items[old.minimum_thread_sequence]
        await conversation.send(DeliverItem(command_id="queued", idempotency_key="queued",
            context=replace(old.context, response_id=None), delivery_id="queued", item_id=source.item_id))
        with pytest.raises(ValueError, match="response identity"):
            await conversation.send(replace(old, command_id="rejected", idempotency_key="rejected"))
        brain.release.set()
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        await wait_for(lambda: any(item.context.response_id == "delivery:queued" for item in core._projected_items.values()))
        assert repair_controller(conversation)._repairable_request.response_id == "delivery:queued"
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
        assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "delivery:queued"


async def test_cancelled_duplicate_waiter_does_not_cancel_the_original_request(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        entered, release = asyncio.Event(), asyncio.Event()
        project = core._turn_from_projection

        async def gated(*args, **kwargs):
            entered.set()
            await release.wait()
            return await project(*args, **kwargs)

        monkeypatch.setattr(core, "_turn_from_projection", gated)
        old = core._published_brain_output.command
        request = replace(old, command_id="concurrent", idempotency_key="concurrent", response_id="concurrent",
            context=replace(old.context, response_id="concurrent"), output_item_id=None)
        owner = asyncio.create_task(conversation.send(request))
        duplicate = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            duplicate = asyncio.create_task(conversation.send(request))
            await asyncio.sleep(0)
            duplicate.cancel()
            with pytest.raises(asyncio.CancelledError):
                await duplicate
            assert not owner.done()
            release.set()
            await owner
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
            assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "concurrent"
        finally:
            release.set()
            owner.cancel()
            if duplicate is not None:
                duplicate.cancel()
            await asyncio.gather(owner, *([duplicate] if duplicate is not None else []), return_exceptions=True)


async def test_completed_explicit_request_replay_does_not_reauthorize_an_old_input(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        old = core._published_brain_output.command
        request = replace(old, command_id="explicit", idempotency_key="explicit", response_id="explicit",
            context=replace(old.context, response_id="explicit"), output_item_id=None)
        await conversation.send(request)
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        await append_manual(conversation)
        await conversation.send(request)
        with pytest.raises(ValueError, match="idempotency key"):
            await conversation.send(replace(request, minimum_thread_sequence=1))
        assert repair_controller(conversation)._repairable_request is None
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: not core._input_pipeline._turn_manager._revisions.reply.delivery_permitted)
        assert len(brain.turns) == 3


@pytest.mark.parametrize("origin", ["typed", "delivery_tool"])
@pytest.mark.parametrize("kind", ["tool", "delegation"])
async def test_explicit_context_repair_cannot_repeat_tool_or_delegation_actions(monkeypatch, origin, kind):
    from server.realtime import AgentDelegationRequestProposed, ResponseFailed, ToolRequested
    from server.realtime.capabilities.brain_streaming import BrainDelegationCall, BrainToolCall
    from server.tools.canonical import LatencyClass
    from tests.realtime.test_automatic_context_repair import RepairBrain

    class RepeatingBrain(RepairBrain):
        async def stream(self, turn):
            if len(self.turns) == 3:
                self.turns.append(turn)
                if kind == "tool":
                    yield BrainToolCall(call_id="fresh-id", tool_name="send", tool_version="1",
                        arguments={}, latency=LatencyClass.FAST)
                else:
                    yield BrainDelegationCall(delegation_request_id="fresh-id", instruction="send")
                return
            async for value in super().stream(turn):
                yield value

    class Execution:
        calls = 0

        async def handle(self, *args):
            self.calls += 1
            raise AssertionError("repair must not authorize tool execution")

        async def submit(self, *args):
            self.calls += 1
            raise AssertionError("repair must not authorize delegation")

    execution = Execution()
    async with automatic_reply(monkeypatch, brain=RepeatingBrain(generation_finished=True),
        tool_handler_factory=lambda: execution, supervisor=execution) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        old = core._published_brain_output.command
        ctx = await append_manual(conversation) if origin == "typed" else replace(old.context, response_id=None)
        source = core._item_by_id("manual") if origin == "typed" else core._projected_items[old.minimum_thread_sequence]
        if origin == "typed":
            await conversation.send(RequestResponse(command_id="explicit", idempotency_key="explicit", context=ctx,
                response_id="explicit", minimum_thread_sequence=source.sequence))
        else:
            tool_ctx = replace(ctx, response_id=old.response_id, call_id="finished-call")
            await conversation.send(AppendItem(command_id="tool-source", idempotency_key="tool-source", context=tool_ctx,
                draft=ConversationItemDraft(item_id="tool-source", context=tool_ctx, kind=ConversationItemKind.TOOL_RESULT,
                    status=ConversationItemStatus.COMPLETED, producer="test-tool", content=(TextContent("订单已创建"),))))
            source = core._item_by_id("tool-source")
            await conversation.send(DeliverItem(command_id="explicit", idempotency_key="explicit", context=ctx,
                delivery_id="explicit", item_id=source.item_id))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
        await wait_for(lambda: any(isinstance(entry[1], ResponseFailed) and "requires new user input" in entry[1].error
            for entry in conversation._events._queue))
        assert brain.turns[-1].context_repair
        assert execution.calls == 0
        assert not any(isinstance(entry[1], (ToolRequested, AgentDelegationRequestProposed))
            for entry in conversation._events._queue)


@pytest.mark.parametrize("repaired", [False, True])
async def test_internal_request_replay_cannot_restore_old_authority(monkeypatch, repaired):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        if repaired:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=1500))
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        old = core._published_brain_output.command
        calls = len(brain.turns)
        await append_manual(conversation)
        await conversation.send(old)
        assert repair_controller(conversation)._repairable_request is None
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: not core._input_pipeline._turn_manager._revisions.reply.delivery_permitted)
        assert len(brain.turns) == calls


async def test_failed_new_request_restores_a_delivery_started_during_its_wait(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        controller = repair_controller(conversation)
        delivery_entered, delivery_release = asyncio.Event(), asyncio.Event()
        request_entered, request_release = asyncio.Event(), asyncio.Event()
        handle, project = controller._handle_event, core._turn_from_projection

        async def gated_event(event):
            if isinstance(event, ItemDeliveryStarted) and event.delivery_id == "pending":
                delivery_entered.set()
                await delivery_release.wait()
            await handle(event)

        async def failing_projection(*args, **kwargs):
            request_entered.set()
            await request_release.wait()
            raise ValueError("controlled projection failure")

        monkeypatch.setattr(controller, "_handle_event", gated_event)
        old = core._published_brain_output.command
        source = core._projected_items[old.minimum_thread_sequence]
        task = None
        try:
            await conversation.send(DeliverItem(command_id="pending", idempotency_key="pending",
                context=replace(old.context, response_id=None), delivery_id="pending", item_id=source.item_id))
            await asyncio.wait_for(delivery_entered.wait(), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            monkeypatch.setattr(core, "_turn_from_projection", failing_projection)
            task = asyncio.create_task(conversation.send(replace(old, command_id="failed", idempotency_key="failed",
                response_id="failed", context=replace(old.context, response_id="failed"), output_item_id=None)))
            await asyncio.wait_for(request_entered.wait(), 1)
            delivery_release.set()
            await wait_for(lambda: any(item.context.response_id == "delivery:pending" for item in core._projected_items.values()))
            request_release.set()
            with pytest.raises(ValueError, match="controlled projection failure"):
                await task
            monkeypatch.setattr(core, "_turn_from_projection", project)
            assert controller._repairable_request.response_id == "delivery:pending"
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
            assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "delivery:pending"
        finally:
            delivery_release.set()
            request_release.set()
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("mode", [DeliveryMode.MODEL_RESPONSE, DeliveryMode.DISPLAY_ONLY])
async def test_failed_delivery_alias_does_not_erase_the_original_admission(monkeypatch, mode):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _previous, first, _):
        controller = repair_controller(conversation)
        entered, release = asyncio.Event(), asyncio.Event()
        handle = controller._handle_event

        async def gated(event):
            if isinstance(event, ItemDeliveryStarted) and event.delivery_id == "same":
                entered.set()
                await release.wait()
            await handle(event)

        monkeypatch.setattr(controller, "_handle_event", gated)
        old = core._published_brain_output.command
        source = core._projected_items[old.minimum_thread_sequence]
        delivery = DeliverItem(command_id="same", idempotency_key="same", delivery_id="same",
            context=replace(old.context, response_id=None), item_id=source.item_id)
        try:
            await conversation.send(delivery)
            await asyncio.wait_for(entered.wait(), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            with pytest.raises(ValueError if mode is DeliveryMode.MODEL_RESPONSE else ContextVisibilityError):
                await conversation.send(replace(delivery, command_id="bad-alias", idempotency_key="bad-alias",
                    mode=mode, item_id="not-projected"))
            release.set()
            await wait_for(lambda: any(item.context.response_id == "delivery:same" for item in core._projected_items.values()))
            assert controller._repairable_request.response_id == "delivery:same"
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
                generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
            assert core._input_pipeline._turn_manager._revisions.reply.supersedes_response_id == "delivery:same"
        finally:
            release.set()


async def test_failed_response_alias_cannot_change_the_original_output_item(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, _bridge, brain, _journal, _previous, _first, _):
        controller = repair_controller(conversation)
        entered, release = asyncio.Event(), asyncio.Event()
        handle = controller._handle_event

        async def gated(event):
            if isinstance(event, ResponseStarted) and event.response_id == "same":
                entered.set()
                await release.wait()
            await handle(event)

        monkeypatch.setattr(controller, "_handle_event", gated)
        old = core._published_brain_output.command
        request = replace(old, command_id="same", idempotency_key="same", response_id="same",
            context=replace(old.context, response_id="same"), output_item_id=None)
        try:
            await conversation.send(request)
            await asyncio.wait_for(entered.wait(), 1)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            original_item_id = core._published_brain_output.command.output_item_id
            with pytest.raises(ValueError):
                await conversation.send(replace(request, command_id="bad-alias", idempotency_key="bad-alias",
                    output_item_id="wrong-output"))
            release.set()
            await wait_for(lambda: any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                and item.context.response_id == "same" for item in core._projected_items.values()))
            item = next(item for item in core._projected_items.values()
                if item.kind is ConversationItemKind.ASSISTANT_OUTPUT and item.context.response_id == "same")
            assert item.item_id == original_item_id
        finally:
            release.set()
