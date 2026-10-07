"""Journal-first control plane for a stateful Realtime Conversation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from server.conversation_journal import ConversationJournal, JournalScope
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.realtime.protocol.commands import (
    AppendItem,
    OutputStopFact,
    ProjectCommittedItem,
    RealtimeCommand,
)
from server.realtime.protocol.engine import (
    RealtimeConversation,
    is_output_context_current,
    is_output_deliverable,
    is_sentence_permit_current,
    observe_output_admitted,
    observe_saved_output_stop,
)
from server.realtime.protocol.events import AudioDelta, RealtimeEvent, SpeechAudioDelta
from server.realtime.scope import conversation_scope


class JournalCommittedProjector:
    """Serialize Journal projection and fill any committed sequence gaps.

    Journal writers such as the WebSocket bridge and Fast Tool Loop may commit
    concurrently.  Engines still require one contiguous projection stream, so
    every writer shares this coordinator instead of projecting its own latest
    item directly.
    """

    def __init__(
        self,
        *,
        context: InteractionContext,
        journal: ConversationJournal,
        engine_conversation: RealtimeConversation,
        projected_through: int = 0,
    ) -> None:
        if projected_through < 0:
            raise ValueError("projected_through must be non-negative")
        self._context = context
        self._journal = journal
        self._engine_conversation = engine_conversation
        self._projected_through = projected_through
        self._lock = asyncio.Lock()

    async def send(self, command: ProjectCommittedItem) -> None:
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        scope = JournalScope.from_context(self._context)
        if JournalScope.from_context(command.context) != scope:
            raise ValueError("command belongs to a different journal scope")

        target = command.item
        async with self._lock:
            if target.sequence <= self._projected_through:
                return
            while self._projected_through < target.sequence:
                items = await self._journal.read(
                    scope,
                    after_sequence=self._projected_through,
                    limit=1000,
                )
                pending = tuple(
                    item for item in items if item.sequence <= target.sequence
                )
                if not pending or pending[0].sequence != self._projected_through + 1:
                    raise RuntimeError(
                        "conversation journal is missing thread sequence "
                        f"{self._projected_through + 1}"
                    )
                for item in pending:
                    if item.sequence == target.sequence and item.item_digest != target.item_digest:
                        raise ValueError(
                            "projected item does not match the committed Journal item"
                        )
                    await self._engine_conversation.send(
                        ProjectCommittedItem(
                            command_id=f"project:{item.item_id}:{item.sequence}",
                            idempotency_key=f"project:{item.item_id}:{item.sequence}",
                            context=self._context,
                            item=item,
                        )
                    )
                    self._projected_through = item.sequence


class JournaledRealtimeConversation:
    """Commits semantic items before exposing them to an engine adapter."""

    def __init__(
        self,
        *,
        context: InteractionContext,
        journal: ConversationJournal,
        engine_conversation: RealtimeConversation,
        committed_projection: JournalCommittedProjector | None = None,
        projected_through: int = 0,
    ) -> None:
        self._context = context
        self._journal = journal
        self._engine_conversation = engine_conversation
        self._committed_projection = committed_projection or JournalCommittedProjector(
            context=context,
            journal=journal,
            engine_conversation=engine_conversation,
            projected_through=projected_through,
        )
        self._append_commands: dict[str, AppendItem] = {}

    async def send(self, command: RealtimeCommand) -> None:
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        if isinstance(command, ProjectCommittedItem):
            raise TypeError("ProjectCommittedItem is control-plane only")
        if not isinstance(command, AppendItem):
            await self._engine_conversation.send(command)
            return
        if JournalScope.from_context(command.context) != JournalScope.from_context(self._context):
            raise ValueError("command belongs to a different journal scope")
        previous = self._append_commands.get(command.idempotency_key)
        if previous is not None:
            if previous != command:
                raise ValueError("idempotency key was reused with different command content")
            return

        result = await self._journal.append(
            command.draft,
            expected_thread_version=command.expected_thread_version,
        )
        await self._committed_projection.send(
            ProjectCommittedItem(
                command_id=f"project:{result.item.item_id}:{result.item.sequence}",
                idempotency_key=f"project:{result.item.item_id}:{result.item.sequence}",
                context=command.context,
                item=result.item,
            )
        )
        self._append_commands[command.idempotency_key] = command

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._engine_conversation.events()

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit) -> bool:
        return is_sentence_permit_current(self._engine_conversation, permit)

    async def observe_saved_output_stop(self, fact: OutputStopFact) -> None:
        await observe_saved_output_stop(self._engine_conversation, fact)

    def observe_output_admitted(self, event: AudioDelta | SpeechAudioDelta) -> None:
        observe_output_admitted(self._engine_conversation, event)

    def output_context_current(self, event: RealtimeEvent) -> bool:
        return is_output_context_current(self._engine_conversation, event)

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return is_output_deliverable(self._engine_conversation, event)

    async def close(self) -> None:
        await self._engine_conversation.close()
