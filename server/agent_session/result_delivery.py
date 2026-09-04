"""Bridge durable Agent-result outbox messages into active Realtime conversations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from server.agent_session.supervisor import AGENT_RESULT_MESSAGE_TYPE
from server.conversation_journal import ConversationItem, ConversationItemDraft, JournalScope
from server.persistence.outbox import OutboxMessage
from server.persistence.unit_of_work import AgentPersistence
from server.realtime.protocol.commands import AppendItem, DeliverItem
from server.realtime.registry import ActiveRealtimeConversations


@dataclass(frozen=True, slots=True)
class AgentResultDelivery:
    message: OutboxMessage
    delivered: bool
    error: str | None = None


class AgentResultDeliveryWorker:
    """Claims committed results and admits them to the Realtime delivery queue."""

    def __init__(
        self,
        *,
        persistence: AgentPersistence,
        conversations: ActiveRealtimeConversations,
        lease_seconds: float = 30,
        retry_delay_seconds: float = 1,
    ) -> None:
        if lease_seconds <= 0 or retry_delay_seconds < 0:
            raise ValueError("delivery lease must be positive and retry delay non-negative")
        self._persistence = persistence
        self._conversations = conversations
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def deliver_once(
        self,
        *,
        owner: str,
        limit: int = 10,
    ) -> tuple[AgentResultDelivery, ...]:
        if not owner or limit < 1:
            raise ValueError("delivery owner must be non-empty and limit positive")
        messages = await self._persistence.outbox.claim(
            owner=owner,
            limit=limit,
            lease_seconds=self._lease_seconds,
            message_types=frozenset({AGENT_RESULT_MESSAGE_TYPE}),
        )
        results: list[AgentResultDelivery] = []
        for message in messages:
            results.append(await self._deliver(message, owner=owner))
        return tuple(results)

    async def _deliver(
        self,
        message: OutboxMessage,
        *,
        owner: str,
    ) -> AgentResultDelivery:
        try:
            worker_id = _required_string(message, "worker_id")
            item_id = _required_string(message, "conversation_item_id")
            thread_sequence = _required_positive_int(message, "thread_sequence")
            record = await self._persistence.agent_tasks.get(worker_id)
            if record is None:
                raise LookupError(f"Agent task {worker_id!r} no longer exists")
            active = self._conversations.resolve(record.context)
            if active is None:
                raise LookupError("originating Realtime conversation is not connected")
            item = await _read_item(
                self._persistence,
                scope=JournalScope.from_context(record.context),
                item_id=item_id,
                thread_sequence=thread_sequence,
            )
            delivery_context = replace(active.context, worker_id=worker_id)
            await active.conversation.send(
                AppendItem(
                    command_id=f"project-agent-result:{message.outbox_id}",
                    idempotency_key=f"project-agent-result:{message.dedupe_key}",
                    context=delivery_context,
                    draft=_draft_from_item(item),
                )
            )
            await active.conversation.send(
                DeliverItem(
                    command_id=f"deliver-agent-result:{message.outbox_id}",
                    idempotency_key=f"deliver-agent-result:{message.dedupe_key}",
                    context=delivery_context,
                    item_id=item.item_id,
                    delivery_id=message.dedupe_key,
                )
            )
            delivered = await self._persistence.outbox.mark_delivered(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
            )
            return AgentResultDelivery(message=delivered, delivered=True)
        except Exception as error:  # noqa: BLE001 - durable retry boundary
            pending = await self._persistence.outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error=f"{type(error).__name__}: {error}",
                retry_delay_seconds=self._retry_delay_seconds,
            )
            return AgentResultDelivery(
                message=pending,
                delivered=False,
                error=str(error),
            )


async def _read_item(
    persistence: AgentPersistence,
    *,
    scope: JournalScope,
    item_id: str,
    thread_sequence: int,
) -> ConversationItem:
    items = await persistence.journal.read(
        scope,
        after_sequence=thread_sequence - 1,
        limit=1,
    )
    if not items or items[0].sequence != thread_sequence or items[0].item_id != item_id:
        raise LookupError(
            f"Conversation Item {item_id!r} is not at thread sequence {thread_sequence}"
        )
    return items[0]


def _draft_from_item(item: ConversationItem) -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id=item.item_id,
        context=item.context,
        kind=item.kind,
        status=item.status,
        producer=item.producer,
        content=item.content,
        display=item.display,
        spoken=item.spoken,
        visibility=item.visibility,
        parent_item_id=item.parent_item_id,
        provider_metadata=item.provider_metadata,
        schema_version=item.schema_version,
        occurred_at=item.occurred_at,
    )


def _required_string(message: OutboxMessage, key: str) -> str:
    value = message.payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Agent result message has invalid {key}")
    return value


def _required_positive_int(message: OutboxMessage, key: str) -> int:
    value = message.payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"Agent result message has invalid {key}")
    return value
