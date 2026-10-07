"""Actor-issued permission to replace a reply without admitting a new input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from server.core.interaction_context import InteractionContext
from server.core.playback import sample_position_us, validate_sample_position

MAX_CONTEXT_REPAIRS = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyRepairPermit:
    permit_id: str
    context: InteractionContext
    predecessor_response_id: str
    response_id: str
    input_id: str
    input_version: int
    predecessor_reply_version: int
    minimum_thread_sequence: int
    attempt: int
    deadline_ns: int
    source_context: InteractionContext | None = None
    recovery: ReplyRecoveryPlan | None = None

    @property
    def input_context(self) -> InteractionContext:
        return self.source_context or self.context

    def __post_init__(self) -> None:
        if not self.permit_id or not self.predecessor_response_id or not self.input_id or not self.response_id:
            raise ValueError("reply repair requires input, response and permission identities")
        if self.response_id == self.predecessor_response_id:
            raise ValueError("reply repair requires a new response identity")
        if min(self.input_version, self.predecessor_reply_version, self.minimum_thread_sequence, self.deadline_ns) < 1:
            raise ValueError("reply repair requires positive versions, projection and deadline")
        if not 1 <= self.attempt <= MAX_CONTEXT_REPAIRS:
            raise ValueError("reply repair attempt exceeds its bounded budget")
        source = self.input_context
        scope = ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id")
        if (any(getattr(source, name) != getattr(self.context, name) for name in scope)
            or source.turn_id != self.context.turn_id or source.generation > self.context.generation):
            raise ValueError("reply continuation must retain its source user lease")
        if self.recovery is not None:
            plan = self.recovery
            if (self.context != plan.response_context or source != plan.input_context
                or (self.predecessor_response_id, self.response_id, self.input_id, self.input_version, self.predecessor_reply_version) !=
                    (plan.predecessor_response_id, plan.response_context.response_id, plan.input_id, plan.input_version, plan.predecessor_reply_version)
                or self.deadline_ns > plan.deadline_ns):
                raise ValueError("recovery permission must match its original evidence plan")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyRecoveryPlan:
    """Actor planning evidence, not permission to generate or deliver output."""

    plan_id: str
    source_context: InteractionContext
    trigger_context: InteractionContext
    response_context: InteractionContext
    predecessor_response_id: str
    input_id: str
    input_version: int
    predecessor_reply_version: int
    observation_id: str
    transcript_revision: int
    revised_text_sha256: str
    feedback_label: Literal["backchannel", "ignore"]
    feedback_source: Literal["rule", "model"]
    feedback_confidence: float
    stop_command_id: str
    stopped_output_epoch: str
    operation_sequence: int | None
    output_epoch: str
    confirmed_text_end: int
    played_audio_end_us: int
    position_precision: Literal["sample", "unknown"]
    played_position_samples: int | None
    sample_rate_hz: int | None
    deadline_ns: int
    strategy: Literal["regenerate_continuation"] = "regenerate_continuation"
    source_input_context: InteractionContext | None = None

    @property
    def input_context(self) -> InteractionContext:
        return self.source_input_context or self.source_context

    def __post_init__(self) -> None:
        identities = (self.plan_id, self.predecessor_response_id, self.input_id, self.observation_id,
                      self.stop_command_id, self.stopped_output_epoch, self.output_epoch)
        positive = (self.input_version, self.predecessor_reply_version, self.transcript_revision, self.deadline_ns)
        if any(not isinstance(value, str) or not value for value in identities) or any(type(value) is not int or value < 1 for value in positive):
            raise ValueError("recovery planning requires original identities, positive revisions and deadline")
        if (len(self.revised_text_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.revised_text_sha256)
            or self.feedback_label not in {"backchannel", "ignore"} or self.feedback_source not in {"rule", "model"}
            or isinstance(self.feedback_confidence, bool) or not 0 <= self.feedback_confidence <= 1):
            raise ValueError("recovery planning requires full feedback evidence")
        scope_fields = ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id")
        if (any(getattr(self.source_context, name) != getattr(other, name)
                for name in scope_fields for other in (self.trigger_context, self.response_context, self.input_context))
            or self.input_context.turn_id != self.source_context.turn_id
            or self.input_context.generation > self.source_context.generation
            or self.response_context.turn_id != self.source_context.turn_id
            or not self.response_context.response_id or self.response_context.response_id == self.predecessor_response_id
            or self.source_context.response_id not in {None, self.predecessor_response_id}
            or any(type(context.generation) is not int for context in (self.source_context, self.trigger_context, self.response_context))
            or self.response_context.generation <= max(self.source_context.generation, self.trigger_context.generation)
            or self.output_epoch == self.stopped_output_epoch):
            raise ValueError("recovery planning requires a new execution lease and output epoch in the same scope")
        if self.operation_sequence is not None and (type(self.operation_sequence) is not int or self.operation_sequence < 1):
            raise ValueError("recovery planning requires a valid stop operation sequence")
        validate_sample_position(self.played_position_samples, self.sample_rate_hz)
        if (self.position_precision not in {"sample", "unknown"} or self.strategy != "regenerate_continuation"
            or any(type(value) is not int or value < 0 for value in (self.confirmed_text_end, self.played_audio_end_us))
            or (self.position_precision == "sample") != (self.played_position_samples is not None)
            or self.played_position_samples is not None and self.sample_rate_hz is not None
                and sample_position_us(self.played_position_samples, self.sample_rate_hz) != self.played_audio_end_us):
            raise ValueError("recovery planning cannot fabricate sample precision or continuation strategy")
