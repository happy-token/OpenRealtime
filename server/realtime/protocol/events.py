"""Canonical events emitted by a stateful Realtime Conversation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.audio import AudioFrame
from server.realtime.protocol.commands import (
    DeliveryMode,
    DeliveryPriority,
    DeliveryTiming,
    InterruptedContextPolicy,
    PlaybackPrecision,
    SpeechContextPolicy,
)
from server.realtime.protocol.playback import SentenceSpan
from server.tools.canonical import LatencyClass
from server.tools.policy_gateway import ConfirmationChannel, ToolOrigin
from server.turn_policy.states import DialogueState


@dataclass(frozen=True, slots=True, kw_only=True)
class DialogueStateChanged:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    from_state: DialogueState
    to_state: DialogueState
    transition: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.transition:
            raise ValueError("dialogue transition identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantYieldRequested:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    reason: str
    schema_version: int = 1
    speech_started_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason:
            raise ValueError("assistant yield identity and reason must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class InputTranscriptDelta:
    """Latest user-input transcript revision available before turn commit.

    ``text`` is authoritative for display because an ASR provider may replace
    an earlier hypothesis instead of only appending characters.
    """

    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    text: str
    delta: str
    transcript_revision: int
    replaces_previous: bool = False
    audio_timestamp_us: int = 0
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.text or not self.delta:
            raise ValueError("input transcript delta must be non-empty")
        if min(
            self.conversation_sequence,
            self.transcript_revision,
            self.schema_version,
        ) < 1:
            raise ValueError("transcript and event sequences must be positive")
        if self.audio_timestamp_us < 0:
            raise ValueError("input transcript audio timestamp must be non-negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("input transcript timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class InputTranscriptCompleted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    text: str
    transcript_revision: int
    provider_endpoint_observed: bool
    continuation_of_turn_id: str | None = None
    schema_version: int = 1
    speech_ended_ns: int | None = None
    input_id: str | None = None
    input_observation_id: str | None = None
    input_version: int | None = None
    admission_reason: str | None = None
    endpoint_decision: str | None = None
    endpoint_source: str | None = None
    input_relation: str | None = None
    input_relation_source: str | None = None
    related_turn_id: str | None = None
    supersedes_unplayed_reply: bool = False

    def __post_init__(self) -> None:
        if not self.event_id or not self.text:
            raise ValueError("completed input transcript must be non-empty")
        if min(self.conversation_sequence, self.transcript_revision, self.schema_version) < 1:
            raise ValueError("transcript and event sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioPluginDiagnostic:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    plugin_id: str
    diagnostic_type: str
    details: Mapping[str, Any]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.plugin_id or not self.diagnostic_type:
            raise ValueError("audio plugin diagnostic identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class RealtimeCapabilityFailed:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    capability: str
    error: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.capability or not self.error:
            raise ValueError("capability failure identity and error must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechStarted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    source_item_id: str | None
    context_policy: SpeechContextPolicy
    interrupted_context_policy: InterruptedContextPolicy
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id:
            raise ValueError("speech event identity must be non-empty")
        if self.source_item_id == "":
            raise ValueError("source item identity must be non-empty when provided")
        if self.conversation_sequence < 1 or self.schema_version < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechTextAccepted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    text_sequence: int
    delta: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id:
            raise ValueError("speech event identity must be non-empty")
        if self.conversation_sequence < 1 or self.schema_version < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.text_sequence < 1 or not self.delta:
            raise ValueError("accepted speech text must be non-empty and ordered")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechTextCommitted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    spoken_text: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id:
            raise ValueError("speech event identity must be non-empty")
        if self.conversation_sequence < 1 or self.schema_version < 1:
            raise ValueError("event sequence and schema version must be positive")
        if not self.spoken_text:
            raise ValueError("committed speech text must be non-empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechAudioDelta:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    frame: AudioFrame
    segment_index: int
    is_final_for_segment: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id:
            raise ValueError("speech audio identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.segment_index < 0:
            raise ValueError("speech audio segment index must be non-negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechTextAlignment:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    audio_end_us: int
    text_end: int
    audio_start_us: int | None = None
    schema_version: int = 1
    text_end_precision: Literal["exact", "estimated"] = "exact"
    sentence: SentenceSpan | None = None

    def __post_init__(self) -> None:
        if (not self.event_id or not self.speech_id or self.audio_end_us < 0 or self.text_end < 0
                or self.text_end_precision not in {"exact", "estimated"}
                or self.audio_start_us is not None and not 0 <= self.audio_start_us <= self.audio_end_us):
            raise ValueError("invalid speech text alignment")

        if self.sentence is not None and not (
            self.sentence.text_start <= self.text_end <= self.sentence.text_end
            and self.sentence.audio_start_us <= self.audio_end_us <= self.sentence.audio_end_us
        ):
            raise ValueError("alignment lies outside its sentence range")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechAudioCompleted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id:
            raise ValueError("speech audio identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechCancelled:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    accepted_text: str
    reason: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.speech_id or not self.reason:
            raise ValueError("cancelled speech identity and reason must be non-empty")
        if self.conversation_sequence < 1 or self.schema_version < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechPlaybackProgress:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    speech_id: str
    delivered_text_end: int
    delivered_speech_transcript: str
    played_audio_end_us: int
    precision: PlaybackPrecision
    completed: bool
    started: bool = False
    stopped: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if sum((self.started, self.stopped, self.completed)) > 1:
            raise ValueError("playback phase flags are mutually exclusive")
        if not self.event_id or not self.speech_id:
            raise ValueError("playback progress identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.delivered_text_end < 0 or self.played_audio_end_us < 0:
            raise ValueError("playback progress must be non-negative")
        if len(self.delivered_speech_transcript) != self.delivered_text_end:
            raise ValueError("delivered transcript must match its text offset")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemProjected:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    item_id: str
    thread_sequence: int
    thread_version: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.item_id:
            raise ValueError("projected item identity must be non-empty")
        if (
            min(
                self.conversation_sequence,
                self.thread_sequence,
                self.thread_version,
                self.schema_version,
            )
            < 1
        ):
            raise ValueError("projected item sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDeliveryQueued:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    minimum_thread_sequence: int
    mode: DeliveryMode
    timing: DeliveryTiming
    priority: DeliveryPriority
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("item delivery identity must be non-empty")
        if min(self.conversation_sequence, self.minimum_thread_sequence, self.schema_version) < 1:
            raise ValueError("item delivery sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDeliveryStarted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    minimum_thread_sequence: int
    mode: DeliveryMode
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("item delivery identity must be non-empty")
        if min(self.conversation_sequence, self.minimum_thread_sequence, self.schema_version) < 1:
            raise ValueError("item delivery sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDeliveryCompleted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    mode: DeliveryMode
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("item delivery identity must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("item delivery sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDeliveryFailed:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    mode: DeliveryMode
    error: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("item delivery identity must be non-empty")
        if not self.error:
            raise ValueError("item delivery failure must carry an error")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("item delivery sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDeliveryCancelled:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    mode: DeliveryMode
    reason: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("item delivery identity must be non-empty")
        if not self.reason:
            raise ValueError("item delivery cancellation must carry a reason")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("item delivery sequences must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDisplayPresented:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    delivery_id: str
    item_id: str
    markdown: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.delivery_id or not self.item_id:
            raise ValueError("display delivery identity must be non-empty")
        if not self.markdown:
            raise ValueError("display delivery content must be non-empty")
        if min(self.conversation_sequence, self.schema_version) < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseRequested:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    minimum_thread_sequence: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.response_id:
            raise ValueError("response request event identity must be non-empty")
        if self.conversation_sequence < 1 or self.schema_version < 1:
            raise ValueError("event sequence and schema version must be positive")
        if self.minimum_thread_sequence < 0:
            raise ValueError("minimum_thread_sequence must be non-negative")
        if self.context.response_id != self.response_id:
            raise ValueError("response request context must carry the same response_id")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")


def _validate_response_event(
    *,
    context: InteractionContext,
    event_id: str,
    response_id: str,
    conversation_sequence: int,
    response_sequence: int,
    schema_version: int,
    occurred_at: datetime,
) -> None:
    if not event_id or not response_id:
        raise ValueError("response event identity must be non-empty")
    if context.response_id != response_id:
        raise ValueError("response event context must carry the same response_id")
    if min(conversation_sequence, response_sequence, schema_version) < 1:
        raise ValueError("response event sequences must be positive")
    if occurred_at.tzinfo is None:
        raise ValueError("event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseStarted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    schema_version: int = 1
    input_id: str | None = None
    input_version: int | None = None
    reply_version: int | None = None
    supersedes_response_id: str | None = None

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DisplayContentDelta:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    delta: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.delta:
            raise ValueError("display content delta must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class SpokenContentDelta:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    delta: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.delta:
            raise ValueError("spoken content delta must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioDelta:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    frame: AudioFrame
    segment_index: int
    speech_id: str | None = None
    is_final_for_segment: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if self.segment_index < 0:
            raise ValueError("audio segment index must be non-negative")
        if self.speech_id == "":
            raise ValueError("speech identity must be non-empty when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseCompleted:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseCancelled:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    reason: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.reason:
            raise ValueError("response cancellation reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseFailed:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    error: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.error:
            raise ValueError("response failure must carry an error")


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolRequested:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    call_id: str
    tool_name: str
    tool_version: str
    arguments: Mapping[str, Any]
    latency: LatencyClass = LatencyClass.FAST
    origin: ToolOrigin = ToolOrigin.PIPELINE_BRAIN
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.call_id or not self.tool_name or not self.tool_version:
            raise ValueError("tool request identity must be non-empty")
        if self.context.call_id != self.call_id:
            raise ValueError("tool request context must carry the same call_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentDelegationRequestProposed:
    """Untrusted Engine proposal that still requires control-plane admission."""

    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    delegation_request_id: str
    instruction: str
    agent_name: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.delegation_request_id or not self.instruction:
            raise ValueError("delegation proposal identity and instruction must be non-empty")
        if self.context.worker_id is not None:
            raise ValueError("delegation proposal cannot claim an accepted worker_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentDelegationRequested:
    """Authoritative acknowledgement emitted after Supervisor commitment."""

    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    worker_id: str
    instruction: str
    agent_name: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if not self.worker_id or not self.instruction:
            raise ValueError("delegation request identity and instruction must be non-empty")
        if self.context.worker_id != self.worker_id:
            raise ValueError("delegation request context must carry the same worker_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmationRequested:
    event_id: str
    context: InteractionContext
    conversation_sequence: int
    occurred_at: datetime
    response_id: str
    response_sequence: int
    confirmation_id: str
    action_digest: str
    summary: str
    required_channel: ConfirmationChannel
    expires_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_response_event(
            context=self.context,
            event_id=self.event_id,
            response_id=self.response_id,
            conversation_sequence=self.conversation_sequence,
            response_sequence=self.response_sequence,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
        )
        if (
            not self.confirmation_id
            or len(self.action_digest) != 64
            or not self.summary
        ):
            raise ValueError(
                "confirmation request identity, digest, and summary must be valid"
            )
        if self.context.confirmation_id != self.confirmation_id:
            raise ValueError("confirmation request context must carry the same confirmation_id")
        if self.expires_at.tzinfo is None:
            raise ValueError("confirmation expiry must be timezone-aware")


RealtimeEvent = (
    AudioPluginDiagnostic
    | RealtimeCapabilityFailed
    | AssistantYieldRequested
    | DialogueStateChanged
    | InputTranscriptDelta
    | InputTranscriptCompleted
    | SpeechStarted
    | SpeechTextAccepted
    | SpeechTextCommitted
    | SpeechAudioDelta
    | SpeechAudioCompleted
    | SpeechTextAlignment
    | SpeechCancelled
    | SpeechPlaybackProgress
    | ItemProjected
    | ItemDeliveryQueued
    | ItemDeliveryStarted
    | ItemDeliveryCompleted
    | ItemDeliveryFailed
    | ItemDeliveryCancelled
    | ItemDisplayPresented
    | ResponseRequested
    | ResponseStarted
    | DisplayContentDelta
    | SpokenContentDelta
    | AudioDelta
    | ResponseCompleted
    | ResponseCancelled
    | ResponseFailed
    | ToolRequested
    | AgentDelegationRequestProposed
    | AgentDelegationRequested
    | ConfirmationRequested
)
