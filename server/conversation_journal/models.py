"""Canonical semantic records owned by the Conversation Journal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias

from server.core.interaction_context import InteractionContext


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationItemKind(StrEnum):
    SESSION_OPENED = "session.opened"
    SESSION_RESUMED = "session.resumed"
    SESSION_CLOSED = "session.closed"
    USER_INPUT = "user.input"
    ASSISTANT_OUTPUT = "assistant.output"
    TOOL_REQUESTED = "tool.requested"
    TOOL_RESULT = "tool.result"
    DELEGATION_REQUESTED = "delegation.requested"
    DELEGATION_PROGRESS = "delegation.progress"
    DELEGATION_RESULT = "delegation.result"
    CONFIRMATION_REQUESTED = "confirmation.requested"
    CONFIRMATION_DECIDED = "confirmation.decided"
    CONTEXT_SUMMARY = "context.summary"
    CORRECTION = "context.correction"
    REDACTION = "context.redaction"


class ConversationItemStatus(StrEnum):
    COMMITTED = "committed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ConversationVisibility(StrEnum):
    USER = "user"
    MODEL = "model"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text content must be non-empty")

    def to_payload(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text, "language": self.language}


@dataclass(frozen=True, slots=True)
class ArtifactReferenceContent:
    artifact_id: str
    media_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.media_type:
            raise ValueError("artifact identity and media_type must be non-empty")
        if self.size_bytes < 0 or len(self.sha256) != 64:
            raise ValueError("artifact size must be non-negative and sha256 must be 64 characters")

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "artifact_reference",
            "artifact_id": self.artifact_id,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True, init=False)
class StructuredContent:
    """A JSON object captured immutably through canonical serialization."""

    canonical_json: str

    def __init__(self, value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise ValueError("structured content must be a JSON object")
        try:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("structured content must be JSON serializable") from error
        object.__setattr__(self, "canonical_json", canonical)

    @property
    def value(self) -> dict[str, Any]:
        decoded = json.loads(self.canonical_json)
        if not isinstance(decoded, dict):  # pragma: no cover - constructor guarantees this
            raise ValueError("structured content did not decode to an object")
        return decoded

    def to_payload(self) -> dict[str, Any]:
        return {"type": "structured", "value": self.value}


ConversationContent: TypeAlias = TextContent | ArtifactReferenceContent | StructuredContent


@dataclass(frozen=True, slots=True)
class DisplayContent:
    markdown: str

    def __post_init__(self) -> None:
        if not self.markdown:
            raise ValueError("display content must be non-empty")

    def to_payload(self) -> dict[str, str]:
        return {"markdown": self.markdown}


@dataclass(frozen=True, slots=True)
class SpokenContent:
    text: str
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("spoken content must be non-empty")

    def to_payload(self) -> dict[str, str | None]:
        return {"text": self.text, "language": self.language}


@dataclass(frozen=True, slots=True)
class AssistantContent:
    semantic: tuple[ConversationContent, ...]
    display: DisplayContent | None = None
    spoken: SpokenContent | None = None

    def __post_init__(self) -> None:
        if not self.semantic:
            raise ValueError("assistant semantic content must be non-empty")


@dataclass(frozen=True, slots=True)
class JournalScope:
    tenant_id: str
    user_id: str
    thread_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.user_id or not self.thread_id:
            raise ValueError("journal scope identity fields must be non-empty")

    @classmethod
    def from_context(cls, context: InteractionContext) -> JournalScope:
        return cls(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            thread_id=context.thread_id,
        )


@dataclass(frozen=True, slots=True)
class SessionInputEvidencePage:
    items: tuple[ConversationItem, ...]
    next_sequence: int | None
    collected: bool


@dataclass(frozen=True, slots=True)
class SessionConversationPage:
    """A bounded original-Session view of user and assistant Journal items."""

    items: tuple[ConversationItem, ...]
    next_sequence: int | None


@dataclass(frozen=True, slots=True)
class ConversationItemDraft:
    item_id: str
    context: InteractionContext
    kind: ConversationItemKind
    status: ConversationItemStatus
    producer: str
    content: tuple[ConversationContent, ...]
    display: DisplayContent | None = None
    spoken: SpokenContent | None = None
    visibility: frozenset[ConversationVisibility] = frozenset(
        {ConversationVisibility.USER, ConversationVisibility.MODEL}
    )
    parent_item_id: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    occurred_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.item_id or not self.producer:
            raise ValueError("conversation item identity and producer must be non-empty")
        if not self.content:
            raise ValueError("conversation item content must be non-empty")
        if not self.visibility:
            raise ValueError("conversation item visibility must be non-empty")
        if self.schema_version < 1:
            raise ValueError("conversation item schema_version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("conversation item occurred_at must be timezone-aware")
        try:
            json.dumps(self.provider_metadata, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("provider metadata must be JSON serializable") from error

    @property
    def scope(self) -> JournalScope:
        return JournalScope.from_context(self.context)

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "context": _context_payload(self.context),
            "kind": self.kind.value,
            "status": self.status.value,
            "producer": self.producer,
            "content": [part.to_payload() for part in self.content],
            "display": self.display.to_payload() if self.display is not None else None,
            "spoken": self.spoken.to_payload() if self.spoken is not None else None,
            "visibility": sorted(value.value for value in self.visibility),
            "parent_item_id": self.parent_item_id,
            "provider_metadata": self.provider_metadata,
            "schema_version": self.schema_version,
        }

    @property
    def item_digest(self) -> str:
        payload = json.dumps(
            self.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationItem:
    item_id: str
    context: InteractionContext
    kind: ConversationItemKind
    status: ConversationItemStatus
    producer: str
    content: tuple[ConversationContent, ...]
    display: DisplayContent | None
    spoken: SpokenContent | None
    visibility: frozenset[ConversationVisibility]
    parent_item_id: str | None
    provider_metadata: dict[str, Any]
    schema_version: int
    occurred_at: datetime
    recorded_at: datetime
    sequence: int
    thread_version: int
    item_digest: str

    @property
    def scope(self) -> JournalScope:
        return JournalScope.from_context(self.context)


@dataclass(frozen=True, slots=True)
class AppendResult:
    item: ConversationItem
    created: bool


@dataclass(frozen=True, slots=True)
class ConversationProjection:
    scope: JournalScope
    items: tuple[ConversationItem, ...]
    thread_version: int


def item_from_draft(
    draft: ConversationItemDraft,
    *,
    sequence: int,
    recorded_at: datetime,
) -> ConversationItem:
    return ConversationItem(
        item_id=draft.item_id,
        context=draft.context,
        kind=draft.kind,
        status=draft.status,
        producer=draft.producer,
        content=draft.content,
        display=draft.display,
        spoken=draft.spoken,
        visibility=draft.visibility,
        parent_item_id=draft.parent_item_id,
        provider_metadata=json.loads(json.dumps(draft.provider_metadata)),
        schema_version=draft.schema_version,
        occurred_at=draft.occurred_at,
        recorded_at=recorded_at,
        sequence=sequence,
        thread_version=sequence,
        item_digest=draft.item_digest,
    )


def _context_payload(context: InteractionContext) -> dict[str, Any]:
    return {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "device_id": context.device_id,
        "voice_session_id": context.voice_session_id,
        "thread_id": context.thread_id,
        "turn_id": context.turn_id,
        "generation": context.generation,
        "response_id": context.response_id,
        "call_id": context.call_id,
        "worker_id": context.worker_id,
        "confirmation_id": context.confirmation_id,
        "handoff_id": context.handoff_id,
    }
