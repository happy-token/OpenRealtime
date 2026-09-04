"""Project bound Tool confirmation decisions into an active Realtime session."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Protocol

from server.core.interaction_context import InteractionContext
from server.realtime.protocol import AppendItem, DeliverItem
from server.realtime.registry import ActiveRealtimeConversations
from server.tools.confirmation import (
    ToolConfirmationDecision,
    ToolConfirmationResolution,
)
from server.tools.policy_gateway import ConfirmationChannel
from server.transport.frames import ConfirmationDecisionFrame


class ToolConfirmationHandler(Protocol):
    async def resolve(
        self,
        decision: ToolConfirmationDecision,
    ) -> ToolConfirmationResolution: ...


class RealtimeConfirmationController:
    """Bind an authenticated Endpoint decision to authority state and delivery."""

    def __init__(
        self,
        *,
        context: InteractionContext,
        conversations: ActiveRealtimeConversations,
        handler: ToolConfirmationHandler,
        channel: ConfirmationChannel,
    ) -> None:
        self._context = context
        self._conversations = conversations
        self._handler = handler
        self._channel = channel

    async def handle(
        self,
        frame: ConfirmationDecisionFrame,
    ) -> ToolConfirmationResolution:
        active = self._conversations.resolve(self._context)
        if active is None:
            raise RuntimeError("Realtime Conversation is not active")
        resolution = await self._handler.resolve(
            ToolConfirmationDecision(
                confirmation_id=frame.confirmation_id,
                action_digest=frame.action_digest,
                context=replace(
                    self._context,
                    confirmation_id=frame.confirmation_id,
                ),
                channel=self._channel,
                approved=frame.approved,
            )
        )
        for draft in resolution.committed_drafts:
            await active.conversation.send(
                AppendItem(
                    command_id=f"append-confirmation-item:{draft.item_id}",
                    idempotency_key=f"append-confirmation-item:{draft.item_id}",
                    context=draft.context,
                    draft=draft,
                )
            )
        result = resolution.result_item
        delivery_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"urn:openrealtime:confirmation-delivery:{frame.confirmation_id}",
            )
        )
        await active.conversation.send(
            DeliverItem(
                command_id=f"deliver-confirmation-result:{frame.confirmation_id}",
                idempotency_key=f"deliver-confirmation-result:{frame.confirmation_id}",
                context=result.context,
                item_id=result.item_id,
                delivery_id=delivery_id,
                output_item_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"urn:openrealtime:confirmation-response:{frame.confirmation_id}",
                    )
                ),
            )
        )
        return resolution
