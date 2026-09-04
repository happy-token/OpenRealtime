"""Model-context projection from immutable content plus delivery facts."""

from __future__ import annotations

from dataclasses import replace

from server.conversation_journal import (
    ConversationContent,
    ConversationItem,
    ConversationJournal,
    ConversationProjection,
    JournalScope,
    StructuredContent,
    TextContent,
)
from server.realtime.protocol.commands import (
    InterruptedContextPolicy,
    SpeechContextPolicy,
)
from server.realtime.speech.delivery import (
    SpeechDeliveryRecord,
    SpeechDeliveryStatus,
    SpeechDeliveryStore,
)


class DeliveryAwareConversationProjector:
    def __init__(
        self,
        *,
        journal: ConversationJournal,
        speech_deliveries: SpeechDeliveryStore,
    ) -> None:
        self._journal = journal
        self._speech_deliveries = speech_deliveries

    async def project_for_model(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> ConversationProjection:
        projection = await self._journal.project_for_model(
            scope,
            after_sequence=after_sequence,
            limit=limit,
        )
        items: list[ConversationItem] = []
        for item in projection.items:
            delivery = await self._speech_deliveries.latest_for_item(item.item_id)
            if delivery is None:
                items.append(item)
                continue
            content = project_assistant_context(item, delivery)
            if content:
                items.append(replace(item, content=content))
        return ConversationProjection(
            scope=projection.scope,
            items=tuple(items),
            thread_version=projection.thread_version,
        )


def project_assistant_context(
    item: ConversationItem,
    delivery: SpeechDeliveryRecord | None,
) -> tuple[ConversationContent, ...]:
    """Project what the model should believe the user actually heard."""

    if delivery is None:
        if item.spoken is not None:
            return (TextContent(item.spoken.text, language=item.spoken.language),)
        return item.content
    if delivery.source_item_id not in (None, item.item_id):
        raise ValueError("speech delivery belongs to a different Conversation Item")
    if delivery.context_policy is SpeechContextPolicy.NONE:
        return ()
    if delivery.status is SpeechDeliveryStatus.COMPLETED:
        return _text_projection(delivery.delivered_speech_transcript)

    policy = delivery.interrupted_context_policy
    if policy is InterruptedContextPolicy.OMIT:
        return ()
    if policy is InterruptedContextPolicy.DELIVERED_ONLY:
        return _text_projection(delivery.delivered_speech_transcript)
    return (
        *_text_projection(delivery.intended_spoken_content),
        StructuredContent(
            {
                "speech_delivery": {
                    "delivered_text": delivery.delivered_speech_transcript,
                    "precision": (
                        delivery.precision.value if delivery.precision is not None else None
                    ),
                    "reason": delivery.reason,
                    "status": delivery.status.value,
                }
            }
        ),
    )


def _text_projection(text: str) -> tuple[ConversationContent, ...]:
    return (TextContent(text),) if text else ()
