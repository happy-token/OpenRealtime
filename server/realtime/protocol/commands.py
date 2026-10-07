"""Canonical commands accepted by a stateful Realtime Conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from server.conversation_journal import ConversationItem, ConversationItemDraft, JournalScope
from server.core.interaction_context import InteractionContext
from server.core.playback import sample_position_us, validate_sample_position
from server.core.reply_repair import ReplyRepairPermit
from server.realtime.protocol.audio import AudioFrame
from server.realtime.protocol.playback import SentenceSpan
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
    output_epoch: str | None = None
    current_sentence: SentenceSpan | None = None
    played_position_samples: int | None = None
    sample_rate_hz: int | None = None
    # Transport replay time is not part of a playback command's semantic identity.
    observed_at_ns: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        validate_sample_position(self.played_position_samples, self.sample_rate_hz)
        if self.played_position_samples is not None and (self.output_epoch is None
            or self.precision is not PlaybackPrecision.SEGMENT):
            raise ValueError("sample clock requires precise playback attachment")
        if self.played_position_samples is not None and self.sample_rate_hz is not None and (
            self.played_audio_end_us != sample_position_us(self.played_position_samples, self.sample_rate_hz)
        ):
            raise ValueError("sample clock and playback microseconds disagree")
        if self.output_epoch is not None and (
            not isinstance(self.output_epoch, str) or not self.output_epoch
            or type(self.observed_at_ns) is not int or self.observed_at_ns <= 0
        ):
            raise ValueError("precise playback requires epoch and server observation clock")
        if self.current_sentence is not None and (
            self.output_epoch is None or self.stopped or self.completed
            or not self.current_sentence.audio_start_us < self.played_audio_end_us < self.current_sentence.audio_end_us
        ):
            raise ValueError("current sentence does not match active playback")
        if sum((self.started, self.stopped, self.completed)) > 1:
            raise ValueError("playback phase flags are mutually exclusive")
        if not self.command_id or not self.idempotency_key or not self.speech_id:
            raise ValueError("playback progress identity must be non-empty")
        if self.delivered_text_end < 0 or self.played_audio_end_us < 0:
            raise ValueError("playback progress must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputStopFact:
    """Server-matched local queue evidence; never a physical speaker guarantee."""

    context: InteractionContext
    stop_command_id: str
    output_epoch: str
    speech_id: str
    state: Literal["STOP_REQUESTED", "STOP_CONFIRMED", "STOP_UNKNOWN"]
    reason: str
    requested_at: datetime
    observed_at: datetime
    received_at: datetime | None = None
    receipt_outcome: Literal["queue_stopped", "unknown", "stale"] | None = None
    played_position_samples: int | None = None
    failure_reason: str | None = None
    operation_sequence: int | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.stop_command_id, self.output_epoch, self.speech_id, self.reason)
        ):
            raise ValueError("stop fact identity and reason must be non-empty")
        if self.operation_sequence is not None and (type(self.operation_sequence) is not int or self.operation_sequence < 1):
            raise ValueError("stop operation sequence must be a positive server ordinal")
        if type(self.context.generation) is not int or self.context.generation < 0:
            raise ValueError("stop fact generation must be a non-negative integer")
        if any(
            not isinstance(value, datetime) or value.tzinfo is None
            for value in (self.requested_at, self.observed_at)
        ):
            raise ValueError("stop fact timestamps must be timezone-aware")
        if self.received_at is not None and (
            not isinstance(self.received_at, datetime) or self.received_at.tzinfo is None
        ):
            raise ValueError("stop receipt timestamp must be timezone-aware")
        if self.state == "STOP_REQUESTED":
            if any(
                value is not None
                for value in (
                    self.received_at,
                    self.receipt_outcome,
                    self.played_position_samples,
                    self.failure_reason,
                )
            ):
                raise ValueError("requested stop cannot contain a receipt or failure")
        elif self.state == "STOP_CONFIRMED":
            if (
                self.receipt_outcome != "queue_stopped"
                or self.received_at is None
                or type(self.played_position_samples) is not int
                or self.played_position_samples < 0
                or self.failure_reason is not None
            ):
                raise ValueError("confirmed stop requires matching local queue receipt")
        elif self.state == "STOP_UNKNOWN":
            if (
                not isinstance(self.failure_reason, str)
                or not self.failure_reason
                or self.played_position_samples is not None
                or self.receipt_outcome not in (None, "unknown", "stale")
                or (self.received_at is None) != (self.receipt_outcome is None)
            ):
                raise ValueError("unknown stop cannot claim confirmed queue position")
        else:
            raise ValueError("invalid stop fact state")


def transition_output_stop_fact(
    current: OutputStopFact | None, candidate: OutputStopFact
) -> OutputStopFact:
    """Preserve first terminal evidence and fence every operation's immutable target."""
    if current is None:
        return candidate
    if (
        current.context,
        current.stop_command_id,
        current.output_epoch,
        current.speech_id,
        current.reason,
        current.requested_at,
        current.operation_sequence,
    ) != (
        candidate.context,
        candidate.stop_command_id,
        candidate.output_epoch,
        candidate.speech_id,
        candidate.reason,
        candidate.requested_at,
        candidate.operation_sequence,
    ):
        raise ValueError("stop operation identity was reused with different content")
    if candidate.state == "STOP_REQUESTED":
        return current
    if current.state == "STOP_REQUESTED":
        return candidate
    if (
        current.state,
        current.receipt_outcome,
        current.played_position_samples,
        current.failure_reason,
    ) != (
        candidate.state,
        candidate.receipt_outcome,
        candidate.played_position_samples,
        candidate.failure_reason,
    ):
        raise ValueError("terminal stop evidence cannot be rewritten")
    return current


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordOutputStop:
    command_id: str
    idempotency_key: str
    context: InteractionContext
    fact: OutputStopFact

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key:
            raise ValueError("stop recording command identity must be non-empty")
        if self.context != self.fact.context:
            raise ValueError("stop recording context must match original output")


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
    repair: ReplyRepairPermit | None = None

    def __post_init__(self) -> None:
        if not self.command_id or not self.idempotency_key or not self.response_id:
            raise ValueError("response request identity must be non-empty")
        if self.minimum_thread_sequence < 0:
            raise ValueError("minimum_thread_sequence must be non-negative")
        if self.context.response_id not in (None, self.response_id):
            raise ValueError("response request does not match context response identity")
        if self.output_item_id == "":
            raise ValueError("response output item identity must be non-empty when provided")
        if self.repair is not None and (
            conversation_scope(self.context) != conversation_scope(self.repair.context)
            or (self.context.turn_id, self.context.generation) != (self.repair.context.turn_id, self.repair.context.generation)
            or self.response_id != self.repair.response_id
            or self.minimum_thread_sequence != self.repair.minimum_thread_sequence
        ):
            raise ValueError("response repair must retain its input lease and use a new reply identity")


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
    | RecordOutputStop
    | AppendItem
    | ProjectCommittedItem
    | DeliverItem
    | RequestResponse
    | CancelResponse
)
