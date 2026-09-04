"""Directory of currently connected Realtime conversations."""

from __future__ import annotations

from dataclasses import dataclass

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.engine import RealtimeConversation
from server.realtime.scope import conversation_scope


@dataclass(frozen=True, slots=True)
class ActiveRealtimeConversation:
    context: InteractionContext
    conversation: RealtimeConversation
    connected: bool = True


class ActiveRealtimeConversations:
    """Process-local routing seam; durable results remain in Journal/Outbox."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str, str, str], ActiveRealtimeConversation] = {}

    def register(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> None:
        scope = conversation_scope(context)
        if scope in self._entries:
            raise ValueError("a Realtime Conversation is already active for this scope")
        self._entries[scope] = ActiveRealtimeConversation(
            context=context,
            conversation=conversation,
        )

    def resolve(self, context: InteractionContext) -> ActiveRealtimeConversation | None:
        active = self._entries.get(conversation_scope(context))
        if active is None or not active.connected:
            return None
        return active

    def suspend(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> None:
        scope = conversation_scope(context)
        active = self._entries.get(scope)
        if active is not None and active.conversation is conversation:
            self._entries[scope] = ActiveRealtimeConversation(
                context=active.context,
                conversation=active.conversation,
                connected=False,
            )

    def resume(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> None:
        scope = conversation_scope(context)
        active = self._entries.get(scope)
        if active is None or active.conversation is not conversation:
            raise ValueError("Realtime Conversation is no longer registered")
        self._entries[scope] = ActiveRealtimeConversation(
            context=active.context,
            conversation=active.conversation,
            connected=True,
        )

    def unregister(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> None:
        scope = conversation_scope(context)
        active = self._entries.get(scope)
        if active is not None and active.conversation is conversation:
            self._entries.pop(scope, None)
