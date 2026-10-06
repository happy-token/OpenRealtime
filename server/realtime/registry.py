"""Directory of currently connected Realtime conversations."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
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
        self._deleting_threads: set[tuple[str, str, str]] = set()

    def register(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> None:
        scope = conversation_scope(context)
        if (context.tenant_id, context.user_id, context.thread_id) in self._deleting_threads:
            raise RuntimeError("conversation history is being deleted; retry opening the session")
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

    def references_thread(self, *, tenant_id: str, user_id: str, thread_id: str) -> bool:
        return any(entry.context.tenant_id == tenant_id and entry.context.user_id == user_id
                   and entry.context.thread_id == thread_id for entry in self._entries.values())

    @contextmanager
    def thread_deletion_guard(self, scopes: Sequence[tuple[str, str, str]]) -> Iterator[frozenset[tuple[str, str, str]]]:
        """Atomically reserve idle threads against registration on the owning event loop."""
        reserved = set()
        for scope in scopes:
            if scope not in self._deleting_threads and not self.references_thread(
                tenant_id=scope[0], user_id=scope[1], thread_id=scope[2],
            ):
                self._deleting_threads.add(scope)
                reserved.add(scope)
        try:
            yield frozenset(reserved)
        finally:
            self._deleting_threads.difference_update(reserved)

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
