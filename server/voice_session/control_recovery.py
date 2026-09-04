"""Atomic, idempotent recovery of model and application control state."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from server.conversation_journal import (
    ConversationItem,
    ConversationItemKind,
    ConversationJournal,
    JournalScope,
    StructuredContent,
)
from server.voice_session.models import VoiceSessionIdentity

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingConfirmationProjection:
    confirmation_id: str
    action_digest: str
    action_summary: str
    required_channel: str
    expires_at: datetime
    generation: int
    requires_restatement: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if not all((self.confirmation_id, self.action_digest, self.action_summary)):
            raise ValueError("Pending Confirmation projection must be identified")
        if _SHA256_PATTERN.fullmatch(self.action_digest) is None:
            raise ValueError("Pending Confirmation digest must be sha256")
        if self.required_channel not in {"voice", "strong"}:
            raise ValueError("Pending Confirmation channel is unsupported")
        if self.expires_at.tzinfo is None:
            raise ValueError("Pending Confirmation expiry must be timezone-aware")
        if self.generation < 0:
            raise ValueError("Pending Confirmation generation must not be negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlRecoveryState:
    completed_tool_call_ids: tuple[str, ...] = ()
    active_worker_ids: tuple[str, ...] = ()
    pending_confirmation: PendingConfirmationProjection | None = None
    pending_delivery_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for values in (
            self.completed_tool_call_ids,
            self.active_worker_ids,
            self.pending_delivery_ids,
        ):
            if any(not value for value in values) or len(set(values)) != len(values):
                raise ValueError("Control recovery identities must be non-empty and unique")


class ModelContextRestorer(Protocol):
    async def restore(
        self, *, target_thread_sequence: int
    ) -> tuple[int, str]: ...


class ControlStateRestorer(Protocol):
    async def restore(
        self, *, target_thread_sequence: int
    ) -> ControlRecoveryState: ...


class ControlIdentitySource(Protocol):
    async def load(
        self,
        *,
        identity: VoiceSessionIdentity,
        target_thread_sequence: int,
    ) -> tuple[str, ...]: ...


class PendingConfirmationSource(Protocol):
    async def load(
        self,
        *,
        identity: VoiceSessionIdentity,
        target_thread_sequence: int,
    ) -> tuple[PendingConfirmationProjection, ...]: ...


class ControlRecoverySink(Protocol):
    async def apply(
        self,
        *,
        idempotency_key: str,
        state: ControlRecoveryState,
    ) -> None: ...


class JournalControlStateRestorer:
    """Rebuild session control identities from one frozen Journal prefix."""

    def __init__(
        self,
        *,
        identity: VoiceSessionIdentity,
        journal: ConversationJournal,
    ) -> None:
        self._identity = identity
        self._journal = journal
        self._scope = JournalScope(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            thread_id=identity.thread_id,
        )

    async def restore(
        self, *, target_thread_sequence: int
    ) -> ControlRecoveryState:
        if target_thread_sequence < 0:
            raise ValueError("control recovery target must not be negative")
        items = await self._read_prefix(target_thread_sequence)
        completed_tools: dict[str, None] = {}
        active_workers: dict[str, None] = {}
        pending_confirmations: dict[str, PendingConfirmationProjection] = {}
        decided_confirmations: set[str] = set()

        for item in items:
            if item.context.voice_session_id != self._identity.voice_session_id:
                continue
            if item.kind is ConversationItemKind.TOOL_RESULT:
                if item.context.call_id:
                    completed_tools[item.context.call_id] = None
            elif item.kind is ConversationItemKind.DELEGATION_REQUESTED:
                if item.context.worker_id:
                    active_workers[item.context.worker_id] = None
            elif item.kind is ConversationItemKind.DELEGATION_RESULT:
                if item.context.worker_id:
                    active_workers.pop(item.context.worker_id, None)
            elif item.kind is ConversationItemKind.CONFIRMATION_REQUESTED:
                projection = _pending_confirmation(item)
                if projection.confirmation_id not in decided_confirmations:
                    pending_confirmations[projection.confirmation_id] = projection
            elif item.kind is ConversationItemKind.CONFIRMATION_DECIDED:
                confirmation_id = _confirmation_id(item)
                decided_confirmations.add(confirmation_id)
                pending_confirmations.pop(confirmation_id, None)

        now = datetime.now(UTC)
        live_confirmations = tuple(
            projection
            for projection in pending_confirmations.values()
            if projection.expires_at > now
        )
        if len(live_confirmations) > 1:
            raise ValueError("Voice Session can restore only one foreground confirmation")
        return ControlRecoveryState(
            completed_tool_call_ids=tuple(completed_tools),
            active_worker_ids=tuple(active_workers),
            pending_confirmation=(
                live_confirmations[0] if live_confirmations else None
            ),
        )

    async def _read_prefix(
        self,
        target_thread_sequence: int,
    ) -> tuple[ConversationItem, ...]:
        if target_thread_sequence == 0:
            return ()
        after_sequence = 0
        restored: list[ConversationItem] = []
        while after_sequence < target_thread_sequence:
            page = await self._journal.read(
                self._scope,
                after_sequence=after_sequence,
                limit=min(1000, target_thread_sequence - after_sequence),
            )
            if not page:
                break
            for item in page:
                if item.sequence > target_thread_sequence:
                    return tuple(restored)
                restored.append(item)
            after_sequence = page[-1].sequence
        if after_sequence < target_thread_sequence:
            raise ValueError("control recovery Journal prefix is incomplete")
        return tuple(restored)


class AuthoritativeControlStateRestorer:
    def __init__(
        self,
        *,
        identity: VoiceSessionIdentity,
        completed_tools: ControlIdentitySource,
        active_workers: ControlIdentitySource,
        pending_confirmations: PendingConfirmationSource,
        pending_deliveries: ControlIdentitySource,
    ) -> None:
        self._identity = identity
        self._completed_tools = completed_tools
        self._active_workers = active_workers
        self._pending_confirmations = pending_confirmations
        self._pending_deliveries = pending_deliveries

    async def restore(
        self, *, target_thread_sequence: int
    ) -> ControlRecoveryState:
        tools, workers, confirmations, deliveries = await asyncio.gather(
            self._completed_tools.load(
                identity=self._identity,
                target_thread_sequence=target_thread_sequence,
            ),
            self._active_workers.load(
                identity=self._identity,
                target_thread_sequence=target_thread_sequence,
            ),
            self._pending_confirmations.load(
                identity=self._identity,
                target_thread_sequence=target_thread_sequence,
            ),
            self._pending_deliveries.load(
                identity=self._identity,
                target_thread_sequence=target_thread_sequence,
            ),
        )
        if len(confirmations) > 1:
            raise ValueError("Voice Session can restore only one foreground confirmation")
        return ControlRecoveryState(
            completed_tool_call_ids=tools,
            active_worker_ids=workers,
            pending_confirmation=confirmations[0] if confirmations else None,
            pending_delivery_ids=deliveries,
        )


class AtomicVoiceSessionRecovery:
    """Publish recovered control state only after model history reaches one target."""

    def __init__(
        self,
        *,
        identity: VoiceSessionIdentity,
        context_restorer: ModelContextRestorer,
        control_restorer: ControlStateRestorer,
        sink: ControlRecoverySink,
    ) -> None:
        self._identity = identity
        self._context_restorer = context_restorer
        self._control_restorer = control_restorer
        self._sink = sink
        self._completed: dict[int, tuple[int, str]] = {}
        self._lock = asyncio.Lock()

    async def restore(self, *, target_thread_sequence: int) -> tuple[int, str]:
        if target_thread_sequence < 0:
            raise ValueError("Voice Session recovery target must not be negative")
        async with self._lock:
            completed = self._completed.get(target_thread_sequence)
            if completed is not None:
                return completed
            (projected_through, projection_digest), control_state = await asyncio.gather(
                self._context_restorer.restore(
                    target_thread_sequence=target_thread_sequence
                ),
                self._control_restorer.restore(
                    target_thread_sequence=target_thread_sequence
                ),
            )
            if projected_through < target_thread_sequence or not projection_digest:
                raise ValueError("model context restoration did not reach its target")
            await self._sink.apply(
                idempotency_key=(
                    f"voice-recovery:{self._identity.voice_session_id}:"
                    f"{target_thread_sequence}"
                ),
                state=control_state,
            )
            result = (projected_through, projection_digest)
            self._completed[target_thread_sequence] = result
            return result


def _pending_confirmation(item: ConversationItem) -> PendingConfirmationProjection:
    payload = _structured_payload(item)
    try:
        confirmation_id = payload["confirmation_id"]
        action_digest = payload["action_digest"]
        action_summary = payload["action_summary"]
        required_channel = payload["required_channel"]
        expires_at_value = payload["expires_at"]
    except KeyError as error:
        raise ValueError("Confirmation Journal item is incomplete") from error
    if not all(
        isinstance(value, str)
        for value in (
            confirmation_id,
            action_digest,
            action_summary,
            required_channel,
            expires_at_value,
        )
    ):
        raise ValueError("Confirmation Journal item fields have invalid types")
    try:
        expires_at = datetime.fromisoformat(expires_at_value)
    except ValueError as error:
        raise ValueError("Confirmation Journal item expiry is invalid") from error
    return PendingConfirmationProjection(
        confirmation_id=confirmation_id,
        action_digest=action_digest,
        action_summary=action_summary,
        required_channel=required_channel,
        expires_at=expires_at,
        generation=item.context.generation,
    )


def _confirmation_id(item: ConversationItem) -> str:
    value = _structured_payload(item).get("confirmation_id")
    if not isinstance(value, str) or not value:
        raise ValueError("Confirmation decision Journal item is unidentified")
    return value


def _structured_payload(item: ConversationItem) -> dict[str, object]:
    structured = next(
        (part for part in item.content if isinstance(part, StructuredContent)),
        None,
    )
    if structured is None:
        raise ValueError("Confirmation Journal item has no structured content")
    return structured.value
