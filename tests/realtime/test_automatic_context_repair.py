"""Automatic replies must continue under a new identity after late heard facts.

Normalized ASR events and provider/renderer receipts are controlled. The actor,
Managed/Core/Journal/Bridge and automatic turn controller are production code.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
)
from server.realtime import ResponseCompleted, ResponseStarted
from server.realtime.capabilities.asr import CommitAsrInput
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.runtime import RealtimeRuntimeFactory
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.turn_policy.policy import TurnPolicy
from server.voice_session.protocol import PlaybackProgressV2
from tests.realtime.test_coordinated_turn_manager import Endpoint, Interrupt, start, stop, text
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_realtime_websocket_bridge import RecordingTransport, context
from tests.realtime.test_reply_playback_observation import Provider
from tests.realtime.test_reply_revision_coordination import final
from tests.realtime.test_reply_revision_production_delivery import open_core


class RepairBrain:
    def __init__(self, *, generation_finished):
        self.turns = []
        self.generation_finished = generation_finished
        self.release = asyncio.Event()
        self.old_closed = asyncio.Event()

    async def stream(self, turn):
        self.turns.append(turn)
        call = len(self.turns)
        try:
            yield "第一句。第二句。" if call == 1 else f"续答版本{call}。"
            if call == 2 and not self.generation_finished:
                await self.release.wait()
        finally:
            if call == 2:
                self.old_closed.set()


@asynccontextmanager
async def automatic_reply(monkeypatch, *, generation_finished=True, brain=None, timeout_s=None, tool_handler_factory=None, supervisor=None, evidence=False, precise_stop=False):
    brain = brain or RepairBrain(generation_finished=generation_finished)
    journal, store = InMemoryConversationJournal(), InMemorySpeechDeliveryStore()
    core = await open_core(brain=brain, tts=Provider(), speech_deliveries=store, interaction_context=context(),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt(),
                                                           input_evidence_journal=journal if evidence else None))
    if timeout_s is not None:
        core._response_timeout_s = timeout_s
    actor = core._input_pipeline._turn_manager
    asr_send = core._input_pipeline._asr.send

    async def controlled_asr(command):
        if not isinstance(command, CommitAsrInput):
            await asr_send(command)

    monkeypatch.setattr(core._input_pipeline._asr, "send", controlled_asr)

    class Engine:
        async def open(self, **kwargs):
            return core

    conversation = await RealtimeRuntimeFactory(engine=Engine(), journal=journal,
        speech_deliveries=store, active_conversations=ActiveRealtimeConversations(),
        tool_control_handler_factory=tool_handler_factory, agent_task_supervisor=supervisor,
        delegation_request_factory=(lambda event: None) if supervisor is not None else None).open(
            context=context(), profile=None)
    from server.voice_session.endpoint_bridge import _ReconnectableConversation
    slot = _ReconnectableConversation()
    await slot.attach(conversation)
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=slot,
        transport=RecordingTransport(), output_epoch="epoch", precise_output_stop=precise_stop)

    async def submit(value, ctx):
        await start(actor, ctx)
        await text(actor, value, ctx=ctx)
        await stop(actor, ctx)
        await wait_for(lambda: actor.snapshot().commit_pending)
        await final(actor, ctx, value)

    try:
        await submit("说两句", context())
        async with asyncio.timeout(1):
            async for event in conversation.events():
                await bridge.handle_event(event)
                if isinstance(event, ResponseCompleted):
                    first_response = event.response_id
                    break
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing",
            played_position_samples=500))
        await submit("请继续", replace(context(), turn_id="next", generation=2))
        await wait_for(lambda: len(brain.turns) == 2 and core._published_brain_output is not None
            and core._published_brain_output.command.context.turn_id == "next")
        predecessor = actor._revisions.reply
        from server.realtime.control_plane import RealtimeTurnController
        controller = conversation._conversation
        while not isinstance(controller, RealtimeTurnController):
            controller = controller._conversation
        # Lock down the public-semantic boundary before invalidation. A Core
        # task having produced text alone does not mean its wrapper consumed it.
        await wait_for(lambda: (predecessor.response_id in controller._response_drafts
            and bool(controller._response_drafts[predecessor.response_id].display_parts))
            or any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                and item.context.response_id == predecessor.response_id for item in core._projected_items.values()))
        if generation_finished:
            await wait_for(lambda: core._response_task is None)
        yield core, conversation, bridge, brain, journal, predecessor, first_response, submit
    finally:
        brain.release.set()
        await slot.close()


@pytest.mark.parametrize("generation_finished", [False, True])
async def test_late_heard_context_automatically_creates_new_reply_version(monkeypatch, generation_finished):
    async with automatic_reply(monkeypatch, generation_finished=generation_finished) as (
        core, conversation, bridge, brain, journal, predecessor, first_response, _submit,
    ):
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing",
            played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3)
        assert brain.old_closed.is_set(), "replacement must wait for the old provider's actual finally"
        assert "第二句。" in brain.turns[-1].conversation_context
        assert brain.turns[-1].text == "请继续"
        current = core._input_pipeline._turn_manager._revisions.reply
        assert current.response_id != predecessor.response_id
        assert current.supersedes_response_id == predecessor.response_id
        assert current.input_id == predecessor.input_id and current.input_version == predecessor.input_version
        assert current.reply_version == predecessor.reply_version + 1
        await wait_for(lambda: core._response_task is None)
        await wait_for(lambda: sum(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
            for item in core._projected_items.values()) == 3)
        rows = await journal.read(JournalScope.from_context(context()))
        assert sum(item.kind is ConversationItemKind.USER_INPUT for item in rows) == 2
        repaired = [item for item in rows if item.kind is ConversationItemKind.ASSISTANT_OUTPUT][-1]
        assert repaired.provider_metadata["supersedes_response_id"] == predecessor.response_id
        events = [entry[1] for entry in conversation._events._queue]
        assert sum(isinstance(event, ResponseStarted) and event.response_id == current.response_id for event in events) == 1
        assert brain.turns[-1].context_repair
        assert "不得再次请求任何工具或委派" in brain.turns[-1].model_text
        # The same in-flight receipt may be replayed; it cannot create another version.
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing",
            played_position_samples=2000))
        await asyncio.sleep(.02)
        assert len(brain.turns) == 3


async def test_sample_only_progress_does_not_repair_a_valid_reply(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, _conversation, bridge, brain, _journal, predecessor, first_response, _submit):
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=700))
        await asyncio.sleep(.03)
        assert len(brain.turns) == 2
        assert core._input_pipeline.response_revision(predecessor.response_id).delivery_permitted


async def test_expired_original_deadline_does_not_start_a_fresh_repair_timeout(monkeypatch):
    async with automatic_reply(monkeypatch, timeout_s=.12) as (core, _conversation, bridge, brain, _journal, predecessor, first_response, _submit):
        await asyncio.sleep(.15)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: not core._detached_response_tasks)
        assert len(brain.turns) == 2
        assert core._input_pipeline.response_revision(predecessor.response_id).context_repair_permit is None


async def test_new_speech_wins_against_a_repair_waiting_for_actor_preparation(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, _conversation, bridge, brain, _journal, _predecessor, first_response, _submit):
        entered, release = asyncio.Event(), asyncio.Event()
        original = core._input_pipeline.response_started

        async def preparing(*args, **kwargs):
            if kwargs.get("repair") is not None:
                entered.set()
                await release.wait()
            await original(*args, **kwargs)

        monkeypatch.setattr(core._input_pipeline, "response_started", preparing)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=2000))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            actor = core._input_pipeline._turn_manager
            next_context = replace(context(), turn_id="new-question", generation=3)
            await start(actor, next_context)
            release.set()
            await wait_for(lambda: core._response_task is None)
            assert len(brain.turns) == 2
            assert actor._failure is None
            assert actor.snapshot().input_id is not None
            await text(actor, "新的问题", ctx=next_context)
            await stop(actor, next_context)
            await wait_for(lambda: actor.snapshot().commit_pending)
            await final(actor, next_context, "新的问题")
            await wait_for(lambda: len(brain.turns) == 3)
            assert brain.turns[-1].text == "新的问题"
            assert not brain.turns[-1].context_repair
        finally:
            release.set()


@pytest.mark.parametrize("kind", ["tool", "delegation"])
async def test_repair_cannot_repeat_an_action_even_with_a_new_call_identity(monkeypatch, kind):
    from server.realtime.capabilities.brain_streaming import BrainDelegationCall, BrainToolCall
    from server.tools.canonical import LatencyClass

    class RepeatingBrain(RepairBrain):
        async def stream(self, turn):
            if len(self.turns) == 2:
                self.turns.append(turn)
                if kind == "tool":
                    yield BrainToolCall(call_id="new-call-id", tool_name="send", tool_version="1",
                        arguments={}, latency=LatencyClass.FAST)
                else:
                    yield BrainDelegationCall(delegation_request_id="new-work-id", instruction="send")
                return
            async for value in super().stream(turn):
                yield value

    class Execution:
        def __init__(self):
            self.calls = 0

        async def handle(self, *args):
            self.calls += 1
            raise AssertionError("repair must never authorize tool execution")

        async def submit(self, *args):
            self.calls += 1
            raise AssertionError("repair must never authorize delegation")

    execution = Execution()
    async with automatic_reply(monkeypatch, brain=RepeatingBrain(generation_finished=True),
        tool_handler_factory=lambda: execution, supervisor=execution) as (
        core, conversation, bridge, brain, _journal, _predecessor, first_response, _submit,
    ):
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        assert execution.calls == 0
        from server.realtime import AgentDelegationRequestProposed, ResponseFailed, ToolRequested
        await wait_for(lambda: any(isinstance(entry[1], ResponseFailed) and "requires new user input" in entry[1].error
            for entry in conversation._events._queue))
        events = [entry[1] for entry in conversation._events._queue]
        assert not any(isinstance(event, (ToolRequested, AgentDelegationRequestProposed)) for event in events)
        assert any(isinstance(event, ResponseFailed) and "requires new user input" in event.error for event in events)


async def test_repair_sees_a_late_durable_tool_result_without_treating_it_as_user_input(monkeypatch):
    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemStatus,
        TextContent,
    )
    from server.realtime import AppendItem

    async with automatic_reply(monkeypatch) as (_core, conversation, bridge, brain, _journal, predecessor, first_response, _submit):
        tool_context = replace(context(), turn_id="next", generation=2,
            response_id=predecessor.response_id, call_id="executed-call")
        await conversation.send(AppendItem(command_id="tool-result", idempotency_key="tool-result", context=tool_context,
            draft=ConversationItemDraft(item_id="tool-result", context=tool_context,
                kind=ConversationItemKind.TOOL_RESULT, status=ConversationItemStatus.COMPLETED,
                producer="test-tool", content=(TextContent("订单已经创建：ORDER-123"),))))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
            speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3)
        assert brain.turns[-1].text == "请继续"
        assert "订单已经创建：ORDER-123" in brain.turns[-1].conversation_context
        assert "未知执行状态须明确说明" in brain.turns[-1].model_text


async def test_continuous_context_changes_share_one_deadline_and_two_repair_budget(monkeypatch):
    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemStatus,
        TextContent,
    )
    from server.realtime import AppendItem

    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, predecessor, first_response, _submit):
        deadline = core._published_brain_output.deadline_ns
        for samples, calls in [(1000, 3), (2000, 4)]:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
                speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=samples))
            await wait_for(lambda calls=calls: len(brain.turns) == calls and core._response_task is None)
            current = core._input_pipeline._turn_manager._revisions.reply
            assert current.context_repair_attempt == calls - 2
            assert current.context_repair_deadline_ns == deadline
            assert current.reply_version == predecessor.reply_version + calls - 2
        # A genuine result that finishes after the second repair invalidates
        # its context, but cannot reset the lineage's attempt/deadline budget.
        late_context = replace(context(), turn_id="next", generation=2,
            response_id=predecessor.response_id, call_id="late-effect")
        await conversation.send(AppendItem(command_id="late-effect", idempotency_key="late-effect", context=late_context,
            draft=ConversationItemDraft(item_id="late-effect", context=late_context,
                kind=ConversationItemKind.TOOL_RESULT, status=ConversationItemStatus.COMPLETED,
                producer="test-tool", content=(TextContent("迟到结果已经保存"),))))
        await wait_for(lambda: not core._detached_response_tasks)
        assert len(brain.turns) == 4
        current = core._input_pipeline._turn_manager._revisions.reply
        assert not current.delivery_permitted and current.context_repair_permit is None
        assert core._response_task is None


async def test_failed_provider_cleanup_never_admits_an_automatic_replacement(monkeypatch):
    class BadCleanupBrain(RepairBrain):
        async def stream(self, turn):
            try:
                async for value in super().stream(turn):
                    yield value
            finally:
                if len(self.turns) == 2:
                    raise RuntimeError("provider finally failed")

    with pytest.raises(RuntimeError, match="Brain capability close did not confirm provider cleanup"):
        async with automatic_reply(monkeypatch, generation_finished=False,
            brain=BadCleanupBrain(generation_finished=False)) as (
            core, conversation, bridge, brain, _journal, predecessor, first_response, _submit,
        ):
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch",
                speech_id=f"response:{first_response}", generation=1, phase="playing", played_position_samples=2000))
            await wait_for(lambda: core._response_task is None)
            assert core._brain_protocol_failed
            assert len(brain.turns) == 2
            assert core._input_pipeline.response_revision(predecessor.response_id).context_repair_permit is None
            from server.realtime import ResponseFailed
            assert any(isinstance(entry[1], ResponseFailed) and "cleanup failed" in entry[1].error
                for entry in conversation._events._queue)


async def test_feedback_discard_rechecks_a_deferred_context_repair(monkeypatch):
    async with automatic_reply(monkeypatch, generation_finished=False) as (core, _conversation, bridge, brain, _journal, _predecessor, first, _submit):
        actor = core._input_pipeline._turn_manager
        feedback = replace(context(), turn_id='feedback', generation=3)
        await start(actor, feedback)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
            generation=1, phase='playing', played_position_samples=2000))
        await wait_for(lambda: core._response_task is None and not core._detached_response_tasks)
        assert len(brain.turns) == 2
        await text(actor, '嗯。', ctx=feedback)
        await stop(actor, feedback)
        await wait_for(lambda: actor._input is None)
        await wait_for(lambda: len(brain.turns) == 3)
        assert actor._failure is None
        assert brain.turns[-1].text == '请继续' and brain.turns[-1].context_repair


async def test_repair_preparation_uses_the_original_absolute_deadline(monkeypatch):
    async with automatic_reply(monkeypatch, timeout_s=.12) as (core, conversation, bridge, brain, _journal, _predecessor, first, _submit):
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        project = core._context_projector.project_text

        async def gated(items):
            entered.set()
            try:
                await release.wait()
                return await project(items)
            finally:
                cancelled.set()

        monkeypatch.setattr(core._context_projector, 'project_text', gated)
        try:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
                generation=1, phase='playing', played_position_samples=2000))
            await asyncio.wait_for(entered.wait(), .5)
            await asyncio.wait_for(cancelled.wait(), .3)
            from server.realtime import RealtimeCapabilityFailed
            await wait_for(lambda: any(isinstance(entry[1], RealtimeCapabilityFailed)
                and entry[1].capability == 'response_context_repair' for entry in conversation._events._queue))
            assert len(brain.turns) == 2 and core._response_task is None
            release.set()
            monkeypatch.setattr(core._context_projector, 'project_text', project)
            await _submit('新的问题', replace(context(), turn_id='after-timeout', generation=3))
            await wait_for(lambda: len(brain.turns) == 3)
            assert brain.turns[-1].text == '新的问题'
        finally:
            release.set()


class DuplexProvider:
    async def synthesize_duplex(self, texts):
        from server.speech.tts import SynthesizedAudioChunk
        async for value in texts:
            yield SynthesizedAudioChunk(pcm16=b'\x00\x00' * 2000, sample_rate_hz=1000, is_final=False,
                spoken_text=value, spoken_start_us=0, spoken_end_us=2000000, sentence_text=value,
                sentence_start_us=0, sentence_duration_us=2000000, sentence_timebase='speech')


@pytest.mark.parametrize('playing_observed', [False, True])
async def test_repair_waits_for_actual_stop_and_preserves_late_heard_text(monkeypatch, playing_observed):
    from server.realtime import AudioDelta
    monkeypatch.setattr(__import__(__name__, fromlist=['Provider']), 'Provider', DuplexProvider)
    async with automatic_reply(monkeypatch, generation_finished=False) as (core, conversation, bridge, brain, _journal, predecessor, first, _submit):
        async with asyncio.timeout(1):
            async for event in conversation.events():
                await bridge.handle_event(event)
                if isinstance(event, AudioDelta) and event.response_id == predecessor.response_id:
                    break
        speech = f'response:{predecessor.response_id}'
        if playing_observed:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=speech,
                generation=2, phase='playing', played_position_samples=500))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
            generation=1, phase='playing', played_position_samples=2000))
        await wait_for(lambda: core._response_task is None and not core._detached_response_tasks)
        assert len(brain.turns) == 2, 'repair must wait for actual old playback settlement'
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=speech,
            generation=2, phase='stopped', played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3)
        record = await core._speech_deliveries.get(speech)
        assert record.played_audio_end_us == 2000000
        assert record.delivered_speech_transcript == '续答版本2。'
        assert '续答版本2。' in brain.turns[-1].conversation_context


async def test_budgeted_repair_keeps_contiguous_sources_and_ignores_its_own_tail(monkeypatch):
    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemStatus,
        TextContent,
    )
    from server.realtime import AppendItem
    from server.voice_session.context import (
        BudgetedConversationContextProjector,
        ConservativeTokenCounter,
        ContextPolicy,
        HybridContextCompressor,
        InMemorySummaryCheckpointStore,
        SummaryCheckpointValidator,
        SummaryNarrative,
    )

    class Counter(ConservativeTokenCounter):
        def count_item(self, item):
            return 20
        def count_text(self, value):
            return 1 if value else 0

    class Summary:
        async def summarize(self, items):
            return SummaryNarrative(narrative='历史已确认')

    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, predecessor, first, _submit):
        for i in range(4):
            ctx = replace(context(), turn_id='next', generation=2, response_id=predecessor.response_id, call_id=f'call-{i}')
            await conversation.send(AppendItem(command_id=f'tool-{i}', idempotency_key=f'tool-{i}', context=ctx,
                draft=ConversationItemDraft(item_id=f'tool-{i}', context=ctx, kind=ConversationItemKind.TOOL_RESULT,
                    status=ConversationItemStatus.COMPLETED, producer='test', content=(TextContent(f'已执行结果{i}'),))))
        counter, validator = Counter(), SummaryCheckpointValidator()
        policy = ContextPolicy(policy_version='p', context_window_tokens=100, max_output_tokens=10,
            tool_schema_tokens=10, governing_instruction_tokens=10, current_input_tokens=5, safety_margin_tokens=5)
        core._context_projector = BudgetedConversationContextProjector(policy=policy, token_counter=counter,
            checkpoint_store=InMemorySummaryCheckpointStore(validator), checkpoint_validator=validator,
            compressor=HybridContextCompressor(model=Summary(), compressor_model='mock', compressor_version='1',
                prompt_version='1', compression_policy_version='p', token_counter=counter))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
            generation=1, phase='playing', played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        await wait_for(lambda: sum(item.kind is ConversationItemKind.ASSISTANT_OUTPUT for item in core._projected_items.values()) == 3)
        assert core._input_pipeline._turn_manager._revisions.reply.delivery_permitted
        assert len(brain.turns) == 3, 'repair completion must not invalidate itself'
        latest = core._input_pipeline._turn_manager._revisions.reply
        ctx = replace(context(), turn_id='next', generation=2, response_id=latest.response_id, call_id='late')
        await conversation.send(AppendItem(command_id='late', idempotency_key='late', context=ctx,
            draft=ConversationItemDraft(item_id='late', context=ctx, kind=ConversationItemKind.TOOL_RESULT,
                status=ConversationItemStatus.COMPLETED, producer='test', content=(TextContent('新的持久结果'),))))
        await wait_for(lambda: len(brain.turns) == 4 and core._response_task is None)
        assert core._input_pipeline._turn_manager._revisions.reply.delivery_permitted


async def test_actor_uses_one_clock_for_repair_preparation(monkeypatch):
    from types import SimpleNamespace

    from server.realtime.capabilities import coordinated_turn_manager as module
    from server.realtime.capabilities.turn_manager import ObserveSystemResponseStarted
    session = await CoordinatedTurnManagerCapabilityAdapter(TurnPolicy).open(context=context())
    try:
        ledger = session._revisions
        ledger.commit_input(input_id='input', context=context(), text='请继续', transcript_revision=1,
            continuation_of_turn_id=None, admission_reason='test')
        ledger.bind_response('old', context())
        ledger.revoke('old', reason='response_invalidated')
        permit = ledger.offer_context_repair('old', context(), minimum_thread_sequence=1, deadline_ns=100, now_ns=1)
        reads = []
        def clock():
            value = 99 if not reads else 100
            reads.append(value)
            return value
        with monkeypatch.context() as patch:
            patch.setattr(module, 'time', SimpleNamespace(monotonic_ns=clock))
            await session.send(ObserveSystemResponseStarted(response_id=permit.response_id,
                context=replace(context(), response_id=permit.response_id), preparing=True, repair=permit))
        assert session._failure is None and not session._actor.done()
        assert session.response_delivery_allowed(permit.response_id)
        assert reads == [99]
    finally:
        await session.close()


@pytest.mark.parametrize('after_offer', [False, True])
async def test_empty_vad_does_not_permanently_discard_a_repair(monkeypatch, after_offer):
    from server.realtime import ResponseCancelled
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, predecessor, first, _submit):
        actor = core._input_pipeline._turn_manager
        actor._provider._asr_idle_stop_s = .015
        entered, release = asyncio.Event(), asyncio.Event()
        original = core._input_pipeline.response_started
        attempted = []
        async def gated(*args, **kwargs):
            if after_offer and kwargs.get('repair') is not None and not attempted:
                attempted.append(kwargs['repair'])
                entered.set()
                await release.wait()
            await original(*args, **kwargs)
        monkeypatch.setattr(core._input_pipeline, 'response_started', gated)
        ctx = replace(context(), turn_id='empty-vad', generation=3)
        if not after_offer:
            await start(actor, ctx)
        try:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
                generation=1, phase='playing', played_position_samples=2000))
            if after_offer:
                await asyncio.wait_for(entered.wait(), .5)
                await start(actor, ctx)
                release.set()
            await wait_for(lambda: core._response_task is None and not core._detached_response_tasks)
            assert len(brain.turns) == 2
            await stop(actor, ctx)
            await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
            current = actor._revisions.reply
            assert current.input_id == predecessor.input_id
            assert current.input_version == predecessor.input_version
            assert current.context_repair_attempt == 1
            assert current.delivery_permitted and actor._failure is None
            if after_offer:
                assert current.response_id == attempted[0].response_id
                assert not any(isinstance(entry[1], ResponseCancelled) and entry[1].response_id == current.response_id
                    for entry in conversation._events._queue)
        finally:
            release.set()


async def test_naturally_completed_output_does_not_wait_for_a_second_stop(monkeypatch):
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, predecessor, first, _submit):
        async with asyncio.timeout(1):
            async for event in conversation.events():
                await bridge.handle_event(event)
                if isinstance(event, ResponseCompleted) and event.response_id == predecessor.response_id:
                    break
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{predecessor.response_id}",
            generation=2, phase="finished", played_position_samples=2000))
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: len(brain.turns) == 3 and core._response_task is None)
        assert "续答版本2。" in brain.turns[-1].conversation_context


async def test_supplier_preparation_timeout_preserves_its_actual_cause(monkeypatch):
    from server.realtime import RealtimeCapabilityFailed
    async with automatic_reply(monkeypatch) as (core, conversation, bridge, brain, _journal, _predecessor, first, _submit):
        async def failed(items):
            raise TimeoutError("summary store timed out")
        monkeypatch.setattr(core._context_projector, "project_text", failed)
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id=f"response:{first}",
            generation=1, phase="playing", played_position_samples=2000))
        await wait_for(lambda: any(isinstance(entry[1], RealtimeCapabilityFailed)
            and entry[1].capability == "response_context_repair" for entry in conversation._events._queue))
        errors = [entry[1].error for entry in conversation._events._queue
            if isinstance(entry[1], RealtimeCapabilityFailed) and entry[1].capability == "response_context_repair"]
        assert errors == ["summary store timed out"]
        assert len(brain.turns) == 2


@pytest.mark.parametrize('after_offer', [False, True])
async def test_explicit_stop_cancels_deferred_repair_and_late_invalidation(monkeypatch, after_offer):
    async with automatic_reply(monkeypatch, generation_finished=after_offer) as (core, _conversation, bridge, brain, _journal, predecessor, first, _submit):
        actor = core._input_pipeline._turn_manager
        entered, release = asyncio.Event(), asyncio.Event()
        original = core._input_pipeline.response_started
        attempts = []
        async def gated(*args, **kwargs):
            if after_offer and kwargs.get('repair') is not None and not attempts:
                attempts.append(kwargs['repair'])
                entered.set()
                await release.wait()
            await original(*args, **kwargs)
        monkeypatch.setattr(core._input_pipeline, 'response_started', gated)
        ctx = replace(context(), turn_id='explicit-stop', generation=3)
        if not after_offer:
            await start(actor, ctx)
        try:
            await bridge.handle_inbound(PlaybackProgressV2(output_epoch='epoch', speech_id=f'response:{first}',
                generation=1, phase='playing', played_position_samples=2000))
            if after_offer:
                await asyncio.wait_for(entered.wait(), .5)
                await start(actor, ctx)
                release.set()
            await wait_for(lambda: core._response_task is None and not core._detached_response_tasks)
            await text(actor, '别说了', ctx=ctx)
            await stop(actor, ctx)
            await wait_for(lambda: actor._input is None)
            assert len(brain.turns) == 2
            current = actor._revisions.reply
            assert current.response_id == predecessor.response_id and not current.delivery_permitted
            assert current.context_repair_permit is None and actor._deferred_context_repair is None
            await core._input_pipeline.invalidate_response(current.response_id,
                context=core._published_brain_output.command.context, reason='response_invalidated')
            await core._offer_context_repair(current.response_id)
            await asyncio.sleep(.02)
            assert len(brain.turns) == 2 and not actor._revisions.reply.delivery_permitted
        finally:
            release.set()
