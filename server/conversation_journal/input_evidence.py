"""Bounded, confirmed input evidence writes; no semantic or playback decisions."""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from server.conversation_journal.journal import ConversationJournal
from server.conversation_journal.models import (
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    JournalScope,
    StructuredContent,
)
from server.core.interaction_context import InteractionContext


def input_evidence_thread_id(thread_id: str, voice_session_id: str) -> str:
    return f"{thread_id}::input-evidence:{voice_session_id}"


def input_evidence_scope(context: InteractionContext) -> JournalScope:
    return JournalScope(context.tenant_id, context.user_id,
                        input_evidence_thread_id(context.thread_id, context.voice_session_id))


class InputEvidenceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    item_id: str
    size_bytes: int
    durable: bool
    committed: asyncio.Future[ConversationItem]


class InputEvidenceRecorder:
    """One ordered storage worker, separate from the turn actor's decisions.

    A failed/late write freezes this recorder. Failed and queued drafts remain
    available until the session is closed; no successful durability is inferred.
    """

    def __init__(
        self, journal: ConversationJournal, *, context: InteractionContext,
        on_failure: Callable[[str], None], max_pending: int = 32,
        max_pending_bytes: int = 1024 * 1024, max_record_bytes: int = 64 * 1024,
        write_timeout_s: float = 1,
    ) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in (max_pending, max_pending_bytes, max_record_bytes)):
            raise ValueError("evidence queue limits must be positive integers")
        if not math.isfinite(write_timeout_s) or write_timeout_s <= 0:
            raise ValueError("evidence write timeout must be finite and positive")
        self._journal = journal
        self._context = context
        self._on_failure = on_failure
        self._max_pending = max_pending
        self._max_pending_bytes = max_pending_bytes
        self._max_record_bytes = max_record_bytes
        self._write_timeout_s = write_timeout_s
        self._queue: asyncio.Queue[tuple[ConversationItemDraft, EvidenceReceipt]] = asyncio.Queue()
        self._pending = 0
        self._pending_bytes = 0
        self._retained: dict[str, tuple[ConversationItemDraft, EvidenceReceipt]] = {}
        self._closed = False
        self.failure: str | None = None
        self._failed_draft: ConversationItemDraft | None = None
        self._active_write: asyncio.Task[Any] | None = None
        self._worker = asyncio.create_task(self._run(), name="input-evidence-writer")

    def offer(self, input_id: str, event: str, detail: dict[str, Any], *,
              context: InteractionContext | None = None) -> EvidenceReceipt:
        if self._closed or self.failure:
            raise InputEvidenceUnavailable(self.failure or "input evidence recorder is closed")
        context = context or self._context
        if (JournalScope.from_context(context) != JournalScope.from_context(self._context)
                or context.voice_session_id != self._context.voice_session_id):
            raise InputEvidenceUnavailable("input evidence context is outside the recorder scope")
        # Capture immutable data before enqueueing; this is a storage acknowledgement, not a debug log.
        content = StructuredContent({**detail, "schema": "semantic-input-evidence.v1", "input_id": input_id,
                                     "event": event, "source_thread_id": self._context.thread_id,
                                     "generation": context.generation, "turn_id": context.turn_id,
                                     "capture_source": "turn_manager_asr", "durable": bool(getattr(self._journal, "durable", False))})
        size = len(content.canonical_json.encode("utf-8"))
        if size > self._max_record_bytes:
            raise InputEvidenceUnavailable("input evidence record exceeds byte limit")
        if self._pending >= self._max_pending or self._pending_bytes + size > self._max_pending_bytes:
            raise InputEvidenceUnavailable("input evidence queue is full")
        identifier = str(uuid.uuid4())
        scope = input_evidence_scope(self._context)
        draft = ConversationItemDraft(
            item_id=identifier, context=replace(context, thread_id=scope.thread_id),
            kind=ConversationItemKind.CONTEXT_SUMMARY, status=ConversationItemStatus.COMMITTED,
            producer="semantic.input_evidence", content=(content,),
            visibility=frozenset({ConversationVisibility.INTERNAL}),
        )
        future = asyncio.get_running_loop().create_future()
        # Background receipts may not have a waiter; errors are also reported through on_failure.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        receipt = EvidenceReceipt(identifier, size, bool(getattr(self._journal, "durable", False)), future)
        self._pending += 1
        self._pending_bytes += size
        self._retained[identifier] = (draft, receipt)
        self._queue.put_nowait((draft, receipt))
        return receipt

    def _fail(self, reason: str) -> None:
        if self.failure is None:
            self.failure = reason
            for _, receipt in self._retained.values():
                if not receipt.committed.done():
                    receipt.committed.set_exception(InputEvidenceUnavailable(reason))
            self._on_failure(reason)

    async def _run(self) -> None:
        while True:
            draft, receipt = await self._queue.get()
            self._active_write = asyncio.create_task(self._journal.append(draft))
            self._active_write.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            try:
                finished, _ = await asyncio.wait({self._active_write}, timeout=self._write_timeout_s)
                if not finished:
                    self._active_write.cancel()
                    raise InputEvidenceUnavailable("input evidence write timed out")
                result = self._active_write.result()
                if result.item.item_id != draft.item_id or result.item.item_digest != draft.item_digest:
                    raise InputEvidenceUnavailable("input evidence commit acknowledgement does not match")
                if not receipt.committed.done():
                    receipt.committed.set_result(result.item)
                self._pending -= 1
                self._pending_bytes -= receipt.size_bytes
                self._retained.pop(receipt.item_id)
                self._queue.task_done()
                self._active_write = None
            except asyncio.CancelledError:
                if self._active_write is not None:
                    self._active_write.cancel()
                self._failed_draft = draft
                if not receipt.committed.done():
                    receipt.committed.set_exception(InputEvidenceUnavailable("input evidence writer closed"))
                if not self._closed:
                    self._fail("input evidence write was cancelled")
                raise
            except Exception as error:  # noqa: BLE001 - failed receipts report persistence errors without leaking details
                self._failed_draft = draft
                reason = "input evidence write failed: " + type(error).__name__
                if isinstance(error, InputEvidenceUnavailable):
                    reason = str(error)
                if not receipt.committed.done():
                    receipt.committed.set_exception(InputEvidenceUnavailable(reason))
                self._fail(reason)
                return

    async def close(self, *, timeout_s: float = 1) -> int:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("evidence close timeout must be finite and positive")
        self._closed = True
        if self.failure is None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout_s)
            except TimeoutError:
                self._fail("input evidence shutdown did not flush all records")
        self._worker.cancel()
        tasks = {self._worker}
        if self._active_write is not None:
            self._active_write.cancel()
            tasks.add(self._active_write)
        await asyncio.wait(tasks, timeout=0.1)
        # Retain unsaved drafts, but resolve all receipts so no caller waits forever.
        for _, receipt in self._retained.values():
            if not receipt.committed.done():
                receipt.committed.set_exception(InputEvidenceUnavailable(self.failure or "writer closed"))
        return self._pending


async def read_input_evidence(
    journal: ConversationJournal, context: InteractionContext, *, after_sequence: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    items = await journal.read(input_evidence_scope(context), after_sequence=after_sequence, limit=limit)
    records = [{"item_id": item.item_id, "sequence": item.sequence,
                "occurred_at": item.occurred_at.isoformat(), "detail": part.value}
               for item in items for part in item.content
               if item.producer == "semantic.input_evidence" and isinstance(part, StructuredContent)]
    latest = items[-1].sequence if items else after_sequence
    last_sequence = await journal.thread_version(input_evidence_scope(context))
    return {"schema": "semantic-input-evidence.v1", "records": records,
            "next_sequence": latest, "last_sequence": last_sequence, "has_more": latest < last_sequence,
            "durable": bool(getattr(journal, "durable", False))}
