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
