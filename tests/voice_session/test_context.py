from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.conversation_journal.models import item_from_draft
from server.core.interaction_context import InteractionContext
from server.voice_session.context import (
    BudgetedConversationContextProjector,
    ConservativeTokenCounter,
    ContextBudgeter,
    ContextPolicy,
    ConversationProjector,
    HybridContextCompressor,
    InMemorySummaryCheckpointStore,
    JsonSummaryNarrativeModel,
    SummaryCheckpoint,
    SummaryCheckpointValidator,
    SummaryNarrative,
    digest_source_items,
)


class RecordingNarrativeModel:
    async def summarize(self, items):
        assert len(items) == 2
        return SummaryNarrative(
            narrative="用户要求查询天气，工具仍在执行。",
            decisions=("使用天气工具",),
            open_questions=("查询结果是什么",),
        )


def test_context_budget_reserves_required_sections_before_history() -> None:
    policy = ContextPolicy(
        policy_version="phase1-v1",
        context_window_tokens=100,
        max_output_tokens=20,
        tool_schema_tokens=10,
        governing_instruction_tokens=10,
        current_input_tokens=10,
        safety_margin_tokens=10,
    )

    budget = ContextBudgeter(policy).allocate()

    assert budget.history_tokens == 40
    assert budget.compression_trigger_tokens == 28


def test_invalid_summary_never_replaces_the_last_valid_checkpoint() -> None:
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )
    source = item_from_draft(
        ConversationItemDraft(
            item_id="item-1",
            context=context,
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("重要决定"),),
        ),
        sequence=1,
        recorded_at=datetime.now(UTC),
    )
    valid = SummaryCheckpoint(
        checkpoint_id="summary-1",
        narrative="用户做出了一个重要决定。",
        source_sequence_start=1,
        source_sequence_end=1,
        source_digest=digest_source_items((source,)),
        compressor_model="compressor-model",
        compressor_version="1",
        prompt_version="1",
        compression_policy_version="phase1-v1",
        input_tokens=20,
        output_tokens=8,
    )
    store = InMemorySummaryCheckpointStore(SummaryCheckpointValidator())
    store.publish(valid, source_items=(source,))

    invalid = SummaryCheckpoint(
        checkpoint_id="summary-2",
        narrative="被篡改的摘要。",
        source_sequence_start=1,
        source_sequence_end=1,
        source_digest="0" * 64,
        compressor_model="compressor-model",
        compressor_version="1",
        prompt_version="1",
        compression_policy_version="phase1-v1",
        input_tokens=20,
        output_tokens=8,
    )
    with pytest.raises(ValueError, match="source digest"):
        store.publish(invalid, source_items=(source,))

    assert store.latest_valid("phase1-v1") == valid


def test_projector_uses_a_valid_summary_plus_uncompressed_recent_items() -> None:
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )
    now = datetime.now(UTC)
    items = tuple(
        item_from_draft(
            ConversationItemDraft(
                item_id=f"item-{sequence}",
                context=context,
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent(f"第{sequence}条历史信息"),),
            ),
            sequence=sequence,
            recorded_at=now,
        )
        for sequence in range(1, 6)
    )
    checkpoint = SummaryCheckpoint(
        checkpoint_id="summary-1",
        narrative="前三条历史摘要",
        source_sequence_start=1,
        source_sequence_end=3,
        source_digest=digest_source_items(items[:3]),
        compressor_model="compressor-model",
        compressor_version="1",
        prompt_version="1",
        compression_policy_version="phase1-v1",
        input_tokens=30,
        output_tokens=6,
    )
    policy = ContextPolicy(
        policy_version="phase1-v1",
        context_window_tokens=120,
        max_output_tokens=10,
        tool_schema_tokens=5,
        governing_instruction_tokens=5,
        current_input_tokens=5,
        safety_margin_tokens=5,
    )

    projection = ConversationProjector(
        policy=policy,
        token_counter=ConservativeTokenCounter(),
        checkpoint_validator=SummaryCheckpointValidator(),
    ).project(items=items, checkpoint=checkpoint)

    assert projection.checkpoint == checkpoint
    assert [item.sequence for item in projection.recent_items] == [4, 5]
    assert projection.projected_through == 5
    assert projection.token_count <= 90


async def test_compressor_keeps_authoritative_work_references_out_of_model_control() -> None:
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )
    now = datetime.now(UTC)
    items = tuple(
        item_from_draft(
            ConversationItemDraft(
                item_id=item_id,
                context=context,
                kind=kind,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent(text),),
            ),
            sequence=sequence,
            recorded_at=now,
        )
        for sequence, item_id, kind, text in (
            (1, "item-user", ConversationItemKind.USER_INPUT, "帮我查天气"),
            (2, "item-tool", ConversationItemKind.TOOL_REQUESTED, "天气查询"),
        )
    )
    compressor = HybridContextCompressor(
        model=RecordingNarrativeModel(),
        compressor_model="compressor-model",
        compressor_version="1",
        prompt_version="1",
        compression_policy_version="phase1-v1",
        token_counter=ConservativeTokenCounter(),
    )

    checkpoint = await compressor.compress(items)

    assert checkpoint.active_work_refs == ("item-tool",)
    assert checkpoint.source_digest == digest_source_items(items)
    assert checkpoint.decisions == ("使用天气工具",)


async def test_budgeted_context_projector_compresses_instead_of_silently_truncating() -> None:
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )
    now = datetime.now(UTC)
    items = tuple(
        item_from_draft(
            ConversationItemDraft(
                item_id=f"item-{sequence}",
                context=context,
                kind=(
                    ConversationItemKind.USER_INPUT
                    if sequence % 2
                    else ConversationItemKind.ASSISTANT_OUTPUT
                ),
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent(f"第{sequence}条很长的历史信息" * 4),),
            ),
            sequence=sequence,
            recorded_at=now,
        )
        for sequence in range(1, 7)
    )
    policy = ContextPolicy(
        policy_version="phase1-v1",
        context_window_tokens=140,
        max_output_tokens=20,
        tool_schema_tokens=10,
        governing_instruction_tokens=10,
        current_input_tokens=10,
        safety_margin_tokens=10,
    )
    counter = ConservativeTokenCounter()
    projector = BudgetedConversationContextProjector(
        policy=policy,
        token_counter=counter,
        checkpoint_store=InMemorySummaryCheckpointStore(
            SummaryCheckpointValidator()
        ),
        checkpoint_validator=SummaryCheckpointValidator(),
        compressor=HybridContextCompressor(
            model=RecordingNarrativeModelForAnyRange(),
            compressor_model="compressor-model",
            compressor_version="1",
            prompt_version="1",
            compression_policy_version="phase1-v1",
            token_counter=counter,
        ),
    )

    rendered = await projector.project_text(items)

    assert "历史摘要：压缩后的历史" in rendered
    assert "第6条很长的历史信息" in rendered
    assert "第1条很长的历史信息" not in rendered


class RecordingNarrativeModelForAnyRange:
    async def summarize(self, items):
        assert items
        return SummaryNarrative(narrative="压缩后的历史")


class JsonSummaryClient:
    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        assert "JSON" in system_prompt
        assert "item-1" in user_text
        return (
            '{"narrative":"保留事实","decisions":["继续"],'
            '"open_questions":[],"commitments":[]}'
        )


async def test_json_summary_model_requires_a_structured_narrative() -> None:
    model = JsonSummaryNarrativeModel(JsonSummaryClient())

    result = await model.summarize((make_item(1, "内容"),))

    assert result.narrative == "保留事实"
    assert result.decisions == ("继续",)


async def test_two_hundred_turn_context_keeps_latest_turn_without_hidden_truncation() -> None:
    items = tuple(
        make_item(sequence, f"第{sequence}条长会话事实" * 4)
        for sequence in range(1, 401)
    )
    policy = ContextPolicy(
        policy_version="phase1-long-session-v1",
        context_window_tokens=180,
        max_output_tokens=20,
        tool_schema_tokens=10,
        governing_instruction_tokens=10,
        current_input_tokens=10,
        safety_margin_tokens=10,
    )
    counter = ConservativeTokenCounter()
    validator = SummaryCheckpointValidator()
    projector = BudgetedConversationContextProjector(
        policy=policy,
        token_counter=counter,
        checkpoint_store=InMemorySummaryCheckpointStore(validator),
        checkpoint_validator=validator,
        compressor=HybridContextCompressor(
            model=RecordingNarrativeModelForAnyRange(),
            compressor_model="test-compressor",
            compressor_version="1",
            prompt_version="1",
            compression_policy_version=policy.policy_version,
            token_counter=counter,
        ),
    )

    rendered = await projector.project_text(items)

    assert rendered is not None
    assert "历史摘要：压缩后的历史" in rendered
    assert "第400条长会话事实" in rendered
    assert "第1条长会话事实" not in rendered


def make_item(sequence: int, text: str):
    context = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )
    return item_from_draft(
        ConversationItemDraft(
            item_id=f"item-{sequence}",
            context=context,
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent(text),),
        ),
        sequence=sequence,
        recorded_at=datetime.now(UTC),
    )


def checkpoint_for(items, narrative="旧的已听摘要"):
    return SummaryCheckpoint(checkpoint_id="heard-summary", narrative=narrative,
        source_sequence_start=items[0].sequence, source_sequence_end=items[-1].sequence,
        source_digest=digest_source_items(items), compressor_model="test", compressor_version="1",
        prompt_version="1", compression_policy_version="heard-v1", input_tokens=0, output_tokens=0)


def heard_projector(*, history_budget=900, trigger_ratio=.7, compressor=None):
    validator = SummaryCheckpointValidator()
    store = InMemorySummaryCheckpointStore(validator)
    projector = BudgetedConversationContextProjector(
        policy=ContextPolicy(policy_version="heard-v1", context_window_tokens=history_budget,
            max_output_tokens=0, tool_schema_tokens=0, governing_instruction_tokens=0,
            current_input_tokens=0, safety_margin_tokens=0, compression_trigger_ratio=trigger_ratio),
        token_counter=ConservativeTokenCounter(), checkpoint_store=store,
        checkpoint_validator=validator, compressor=compressor)
    return projector, store


async def test_updated_heard_content_invalidates_summary_without_changing_journal_digest():
    from dataclasses import replace

    source = make_item(1, "只听到第一句")
    latest = replace(source, content=(TextContent("也听到了第二句"),))
    projector, store = heard_projector()
    store.publish(checkpoint_for((source,)), source_items=(source,))
    assert latest.item_digest == source.item_digest
    assert digest_source_items((latest,)) != digest_source_items((source,))
    rendered = await projector.project_text((latest, make_item(2, "当前问题")))
    assert "也听到了第二句" in rendered
    assert "旧的已听摘要" not in rendered


def test_recent_projection_digest_changes_with_actual_model_visibility_and_content():
    from dataclasses import replace

    from server.conversation_journal import ConversationVisibility

    source = make_item(1, "第一句")
    policy = ContextPolicy(policy_version="heard-v1", context_window_tokens=900,
        max_output_tokens=0, tool_schema_tokens=0, governing_instruction_tokens=0,
        current_input_tokens=0, safety_margin_tokens=0)
    projector = ConversationProjector(policy=policy, token_counter=ConservativeTokenCounter(),
        checkpoint_validator=SummaryCheckpointValidator())
    original = projector.project(items=(source,), checkpoint=None)
    changed = projector.project(items=(replace(source, content=(TextContent("第二句"),)),), checkpoint=None)
    hidden = projector.project(items=(replace(source, visibility=frozenset({ConversationVisibility.USER})),), checkpoint=None)
    relation = projector.project(items=(replace(source, provider_metadata={"input_relation": "unresolved"}),), checkpoint=None)
    assert len({original.projection_digest, changed.projection_digest, hidden.projection_digest, relation.projection_digest}) == 4
    assert source.item_digest == replace(source, content=(TextContent("第二句"),)).item_digest


async def test_old_in_flight_compression_cannot_supply_a_new_heard_frontier():
    import asyncio
    from dataclasses import replace

    class Model:
        def __init__(self):
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.requests = []

        async def summarize(self, items):
            self.requests.append(items)
            if len(self.requests) == 1:
                self.entered.set()
                await self.release.wait()
            return SummaryNarrative(narrative=items[0].content[0].text)

    model = Model()
    compressor = HybridContextCompressor(model=model, compressor_model="test", compressor_version="1",
        prompt_version="1", compression_policy_version="heard-v1", token_counter=ConservativeTokenCounter())
    projector, store = heard_projector(history_budget=80, trigger_ratio=.1, compressor=compressor)
    source = tuple(make_item(i, "第一句" if i == 1 else "普通记录"*4) for i in range(1, 7))
    latest = (replace(source[0], content=(TextContent("第二句已确认"),)), *source[1:])
    store.publish(checkpoint_for(source[:4], "第一句"), source_items=source[:4])
    task = None
    try:
        await projector.project_text(source)
        await asyncio.wait_for(model.entered.wait(), .5)
        task = asyncio.create_task(projector.project_text(latest))
        await asyncio.sleep(0)
        model.release.set()
        rendered = await asyncio.wait_for(task, 1)
        assert "第二句已确认" in rendered
        assert "第一句" not in rendered
        assert any(request[0].content[0].text == "第二句已确认" for request in model.requests)
    finally:
        model.release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if projector._compression_task is not None:
            await asyncio.gather(projector._compression_task, return_exceptions=True)


async def test_hidden_superseded_records_keep_compression_source_contiguous_without_model_leak():
    import asyncio
    from dataclasses import replace

    from server.conversation_journal import ConversationVisibility

    requests = []

    class Model:
        async def summarize(self, items):
            requests.append(items)
            assert all(ConversationVisibility.MODEL in item.visibility for item in items)
            assert not {"item-2", "item-3"} & {item.item_id for item in items}
            return SummaryNarrative(narrative="可见历史摘要")

    compressor = HybridContextCompressor(model=Model(), compressor_model="test", compressor_version="1",
        prompt_version="1", compression_policy_version="heard-v1", token_counter=ConservativeTokenCounter())
    projector, store = heard_projector(history_budget=120, compressor=compressor)
    source = tuple(make_item(i, "需要保留的历史" * 4) for i in range(1, 21))
    source = tuple(replace(item, visibility=item.visibility - {ConversationVisibility.MODEL},
                          content=(TextContent("已经替换的秘密内容"),)) if item.sequence in {2, 3} else item
                   for item in source)
    try:
        rendered = await projector.project_text(source)
        assert "可见历史摘要" in rendered
        assert "已经替换的秘密内容" not in rendered
        assert requests
        checkpoint = store.latest_valid("heard-v1")
        assert checkpoint.source_sequence_start == 1
        assert checkpoint.source_sequence_end > 3
        covered = tuple(item for item in source if item.sequence <= checkpoint.source_sequence_end)
        SummaryCheckpointValidator().validate(checkpoint, source_items=covered)
        assert [item.sequence for item in covered] == list(range(1, checkpoint.source_sequence_end + 1))
    finally:
        if projector._compression_task is not None:
            await asyncio.gather(projector._compression_task, return_exceptions=True)


@pytest.mark.parametrize("checkpoint_scope", ["none", "prefix", "changed_target"])
async def test_hypothetical_context_does_not_publish_or_consume_fact_compression(checkpoint_scope):
    import asyncio
    from dataclasses import replace

    class NoHypotheticalCompression:
        async def compress(self, items):
            raise AssertionError("hypothetical source reached factual compressor")

    originals = (make_item(1, "已确认历史"), make_item(2, "实际尚未听完"))
    hypothetical = (originals[0], replace(originals[1], content=(TextContent("许可句预计播完"),)))
    projector, store = heard_projector(trigger_ratio=.001, compressor=NoHypotheticalCompression())
    checkpoint = None
    if checkpoint_scope != "none":
        source = originals[:1] if checkpoint_scope == "prefix" else originals
        checkpoint = checkpoint_for(source)
        store.publish(checkpoint, source_items=source)
    release = asyncio.Event()
    async def factual_work():
        await release.wait()
        return checkpoint_for(originals, "事实任务结果")
    worker = asyncio.create_task(factual_work())
    projector._compression_task = worker
    try:
        rendered = await projector.project_hypothetical_text(hypothetical)
        assert "许可句预计播完" in rendered
        assert ("旧的已听摘要" in rendered) is (checkpoint_scope == "prefix")
        assert store.latest_valid("heard-v1") == checkpoint
        assert projector._compression_task is worker
        assert not worker.done()
        assert originals[1].content == (TextContent("实际尚未听完"),)
    finally:
        release.set()
        await worker


async def test_hypothetical_context_over_budget_preserves_factual_checkpoint_and_no_worker():
    from dataclasses import replace

    class NoHypotheticalCompression:
        async def compress(self, items):
            raise AssertionError("over-budget hypothesis must skip instead of compression")

    source = make_item(1, "原来的事实")
    projector, store = heard_projector(history_budget=1, compressor=NoHypotheticalCompression())
    checkpoint = checkpoint_for((source,))
    store.publish(checkpoint, source_items=(source,))
    with pytest.raises(ValueError, match="does not fit"):
        await projector.project_hypothetical_text((replace(source, content=(TextContent("条件计划" * 40),)),))
    assert store.latest_valid("heard-v1") == checkpoint
    assert projector._compression_task is None
