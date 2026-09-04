from __future__ import annotations

from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    DisplayContent,
    InMemoryConversationJournal,
    JournalScope,
    SpokenContent,
    StructuredContent,
    TextContent,
)
from server.conversation_journal.models import item_from_draft, utc_now
from server.core.interaction_context import InteractionContext
from server.realtime import InterruptedContextPolicy, PlaybackPrecision, SpeechContextPolicy
from server.realtime.speech import (
    DeliveryAwareConversationProjector,
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
    SpeechDeliveryStatus,
)
from server.realtime.speech.projection import project_assistant_context


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        response_id="response-1",
    )


def assistant_item():
    return item_from_draft(
        ConversationItemDraft(
            item_id="assistant-1",
            context=context(),
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.INTERRUPTED,
            producer="cascaded-realtime-engine",
            content=(
                TextContent("完整语义内容。"),
                StructuredContent({"details": [1, 2, 3]}),
            ),
            display=DisplayContent(markdown="## 完整内容"),
            spoken=SpokenContent(text="任务已经完成，全部测试通过。"),
        ),
        sequence=1,
        recorded_at=utc_now(),
    )


def interrupted_delivery(
    policy: InterruptedContextPolicy = InterruptedContextPolicy.DELIVERED_ONLY,
) -> SpeechDeliveryRecord:
    return SpeechDeliveryRecord(
        speech_id="speech-1",
        context=context(),
        source_item_id="assistant-1",
        context_policy=SpeechContextPolicy.AUTO,
        interrupted_context_policy=policy,
        intended_spoken_content="任务已经完成，全部测试通过。",
        delivered_speech_transcript="任务已经完成",
        played_audio_end_us=480_000,
        status=SpeechDeliveryStatus.INTERRUPTED,
        precision=PlaybackPrecision.SEGMENT,
        text_committed=True,
        reason="barge_in",
        revision=5,
        updated_at=utc_now(),
    )


def test_default_interrupted_projection_contains_only_confirmed_delivered_speech() -> None:
    projection = project_assistant_context(assistant_item(), interrupted_delivery())

    assert projection == (TextContent("任务已经完成"),)


def test_full_interrupted_projection_keeps_intended_text_and_delivery_state() -> None:
    projection = project_assistant_context(
        assistant_item(),
        interrupted_delivery(InterruptedContextPolicy.FULL_WITH_DELIVERY_STATE),
    )

    assert projection[0] == TextContent("任务已经完成，全部测试通过。")
    assert isinstance(projection[1], StructuredContent)
    assert projection[1].value == {
        "speech_delivery": {
            "delivered_text": "任务已经完成",
            "precision": "segment",
            "reason": "barge_in",
            "status": "interrupted",
        }
    }


@pytest.mark.parametrize(
    "record",
    [
        interrupted_delivery(InterruptedContextPolicy.OMIT),
        replace(interrupted_delivery(), context_policy=SpeechContextPolicy.NONE),
    ],
)
def test_omit_policies_exclude_speech_from_model_context(record: SpeechDeliveryRecord) -> None:
    assert project_assistant_context(assistant_item(), record) == ()


async def test_delivery_aware_projection_keeps_full_display_but_models_only_heard_prefix() -> None:
    journal = InMemoryConversationJournal()
    item = assistant_item()
    await journal.append(
        ConversationItemDraft(
            item_id=item.item_id,
            context=item.context,
            kind=item.kind,
            status=item.status,
            producer=item.producer,
            content=item.content,
            display=item.display,
            spoken=item.spoken,
        )
    )
    deliveries = InMemorySpeechDeliveryStore()
    record = interrupted_delivery()
    await deliveries.start(
        replace(
            record,
            intended_spoken_content="",
            delivered_speech_transcript="",
            played_audio_end_us=0,
            status=SpeechDeliveryStatus.ACTIVE,
            precision=None,
            text_committed=False,
            reason=None,
            revision=1,
        )
    )
    await deliveries.append_text(record.speech_id, record.intended_spoken_content)
    await deliveries.commit_text(record.speech_id)
    await deliveries.report_progress(
        record.speech_id,
        delivered_text_end=len(record.delivered_speech_transcript),
        played_audio_end_us=record.played_audio_end_us,
        precision=record.precision or PlaybackPrecision.SEGMENT,
        completed=False,
    )
    await deliveries.cancel(record.speech_id, reason=record.reason or "barge_in")
    projector = DeliveryAwareConversationProjector(
        journal=journal,
        speech_deliveries=deliveries,
    )

    projection = await projector.project_for_model(JournalScope.from_context(context()))

    assert projection.items[0].content == (TextContent("任务已经完成"),)
    assert projection.items[0].display == DisplayContent(markdown="## 完整内容")
    assert projection.items[0].spoken == SpokenContent(
        text="任务已经完成，全部测试通过。"
    )
