"""Canonical commands accepted by a stateful Realtime Conversation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from server.conversation_journal import ConversationItem, ConversationItemDraft, JournalScope
from server.core.interaction_context import InteractionContext
from server.realtime.protocol.audio import AudioFrame
from server.realtime.scope import conversation_scope


class SpeechContextPolicy(StrEnum):
    AUTO = "auto"
    APPEND = "append"
    NONE = "none"


class InterruptedContextPolicy(StrEnum):
    DELIVERED_ONLY = "delivered_only"
    FULL_WITH_DELIVERY_STATE = "full_with_delivery_state"
    OMIT = "omit"


class PlaybackPrecision(StrEnum):
    EXACT = "exact"
    SEGMENT = "segment"
    ESTIMATED = "estimated"


class DeliveryMode(StrEnum):
    MODEL_RESPONSE = "model_response"
    SPEECH = "speech"
    DISPLAY_ONLY = "display_only"
    SILENT = "silent"


class DeliveryTiming(StrEnum):
    WHEN_IDLE = "when_idle"
    AFTER_RESPONSE = "after_response"
    IMMEDIATE = "immediate"


class DeliveryPriority(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendAudio:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    frame: AudioFrame

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key:
            raise ValueError("audio append command identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class StartSpeech:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    speech_id: str
    source_item_id: str | None = None
    context_policy: SpeechContextPolicy = SpeechContextPolicy.AUTO
    interrupted_context_policy: InterruptedContextPolicy = InterruptedContextPolicy.DELIVERED_ONLY

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("speech command identity must be non-empty")
        if self.source_item_id == "":
            raise ValueError("source item identity must be non-empty when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendSpeechText:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    speech_id: str
    text_sequence: int
    delta: str

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("speech command identity must be non-empty")
        if self.text_sequence < 1:
            raise ValueError("speech text sequence must be positive")
        if not self.delta:
            raise ValueError("speech text delta must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitSpeech:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    speech_id: str

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("speech command identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelSpeech:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    speech_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("speech command identity must be non-empty")
        if not self.reason:
            raise ValueError("speech cancellation reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportPlaybackProgress:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    speech_id: str
    delivered_text_end: int
    played_audio_end_us: int
    precision: PlaybackPrecision = PlaybackPrecision.SEGMENT
    completed: bool = False
    started: bool = False
    stopped: bool = False

    def __post_init__(self) -> None:
        if sum((self.started, self.stopped, self.completed)) > 1:
            raise ValueError("playback phase flags are mutually exclusive")
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("playback progress identity must be non-empty")
        if self.delivered_text_end < 0 or self.played_audio_end_us < 0:
            raise ValueError("playback progress must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendItem:
    """Append a semantic item through the Journal-first control plane."""

    command_id: str
    idempotency_key: str
    context: InteractionContext
    draft: ConversationItemDraft
    expected_thread_version: int | None = None

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key:
            raise ValueError("append item command identity must be non-empty")
        if self.expected_thread_version is not None and self.expected_thread_version < 0:
            raise ValueError("expected_thread_version must be non-negative")
        if self.draft.scope != JournalScope.from_context(self.context):
            raise ValueError("item draft belongs to a different journal scope")
        if conversation_scope(self.draft.context) != conversation_scope(self.context):
            raise ValueError("item draft belongs to a different realtime conversation scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectCommittedItem:
    """Project thread history into the current session after Journal commit.

    The command belongs to the live session; the immutable item may originate
    in an earlier voice session or device within the same authorized thread.
    """

    command_id: str
    idempotency_key: str
    context: InteractionContext
    item: ConversationItem

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key:
            raise ValueError("project item command identity must be non-empty")
        if self.item.scope != JournalScope.from_context(self.context):
            raise ValueError("committed item belongs to a different journal scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliverItem:
    """Schedule presentation of an item already committed and projected."""

    command_id: str
    idempotency_key: str
    context: InteractionContext
    item_id: str
    delivery_id: str
    output_item_id: str | None = None
    mode: DeliveryMode = DeliveryMode.MODEL_RESPONSE
    timing: DeliveryTiming = DeliveryTiming.WHEN_IDLE
    priority: DeliveryPriority = DeliveryPriority.NORMAL

    def __post_init__(self) -> None:
        if not all((self.command_id, self.idempotency_key, self.item_id, self.delivery_id)):
            raise ValueError("item delivery identity must be non-empty")
        if self.output_item_id == "":
            raise ValueError("delivery output item identity must be non-empty when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestResponse:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    response_id: str
    minimum_thread_sequence: int
    output_item_id: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.response_id:
            raise ValueError("response request identity must be non-empty")
        if self.minimum_thread_sequence < 0:
            raise ValueError("minimum_thread_sequence must be non-negative")
        if self.context.response_id not in (None, self.response_id):
            raise ValueError("response request does not match context response identity")
        if self.output_item_id == "":
            raise ValueError("response output item identity must be non-empty when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelResponse:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    response_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.response_id:
            raise ValueError("response cancellation identity must be non-empty")
        if not self.reason:
            raise ValueError("response cancellation reason must be non-empty")
        if self.context.response_id not in (None, self.response_id):
            raise ValueError("response cancellation does not match context response identity")


RealtimeCommand = (
    AppendAudio
    | StartSpeech
    | AppendSpeechText
    | CommitSpeech
    | CancelSpeech
    | ReportPlaybackProgress
    | AppendItem
    | ProjectCommittedItem
    | DeliverItem
    | RequestResponse
    | CancelResponse
)
