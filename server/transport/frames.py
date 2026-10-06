"""Wire frame schema for the Raw WebSocket Transport Adapter.

The module contains the v2 Voice Session control/media frames used by the
production browser path plus non-media application control frames.
Realtime command/event translation belongs to ``server.realtime.transport``;
these models only define validated wire data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.voice_session.protocol import (
    AudioGap,
    InputAudioAck,
    InputAudioFrame,
    InputCaptureDiagnostic,
    InputEpochStarted,
    OutputStopResult,
    PlaybackProgressV2,
    VoiceSessionFailureFrame,
)


class UserTextFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["user_text"] = "user_text"
    text: str
    seq: int | None = None
    timestamp_ms: int | None = None


class CancelAssistantResponseFrame(BaseModel):
    """Explicit user request to stop the active assistant response."""

    model_config = ConfigDict(frozen=True)
    type: Literal["cancel_assistant_response"] = "cancel_assistant_response"


class PlaybackProgressFrame(BaseModel):
    """Client-reported playback truth for one generation's assistant audio.

    `finished=True` means the client's last scheduled audio source actually
    ended — the only real end-of-playback signal in the system. A client that
    sends this opts the session into client-reported playback truth;
    `finished=False` is reserved for
    mid-playback position reporting and is currently ignored.

    Untrusted input like any other inbound frame: see
    the realtime transport bridge checks the generation so a stale report
    cannot end the current turn. See ADR-0037.
    """

    model_config = ConfigDict(frozen=True)
    type: Literal["playback_progress"] = "playback_progress"
    generation: int
    finished: bool
    started: bool = False
    stopped: bool = False
    played_audio_end_us: int | None = Field(default=None, ge=0)


class PlaybackQualityFrame(BaseModel):
    """Aggregated terminal playback diagnostics for one Generation.

    Contains timing counters only. Raw audio, transcript text, and per-chunk
    samples are intentionally excluded so diagnostics remain bounded and safe.
    """

    model_config = ConfigDict(frozen=True)
    type: Literal["playback_quality"] = "playback_quality"
    generation: int = Field(ge=0)
    arrival_jitter_ms: float = Field(ge=0, le=60_000)
    max_chunk_gap_ms: float = Field(ge=0, le=60_000)
    underrun_count: int = Field(ge=0, le=100_000)
    underrun_total_ms: float = Field(ge=0, le=3_600_000)
    chunk_count: int = Field(ge=0, le=1_000_000)


class ClientConnectionQualityFrame(BaseModel):
    """One completed browser-to-OpenRealtime transport outage."""

    model_config = ConfigDict(frozen=True)
    type: Literal["client_connection_quality"] = "client_connection_quality"
    reconnect_count: int = Field(ge=1, le=100_000)
    last_disconnect_ms: float = Field(ge=0, le=3_600_000)
    max_disconnect_ms: float = Field(ge=0, le=3_600_000)


class TtsConfigFrame(BaseModel):
    """Updates speech synthesis presentation for the current session."""

    model_config = ConfigDict(frozen=True)
    type: Literal["tts_config"] = "tts_config"
    provider: Literal["bailian", "doubao"] = "doubao"
    voice: str = Field(min_length=1, max_length=128)
    speech_rate: int = Field(default=0, ge=-50, le=100)
    dialect: Literal[
        "",
        "anhui",
        "cantonese",
        "dongbei",
        "henan",
        "hunan",
        "shaanxi",
        "shandong",
        "sichuan",
    ] = ""


class AvatarPersonaConfigFrame(BaseModel):
    """Selects a trusted Persona directly or through an Avatar link."""

    model_config = ConfigDict(frozen=True)
    type: Literal["avatar_persona_config"] = "avatar_persona_config"
    avatar_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$",
    )
    persona_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{1,63}$",
    )


class ToolConfigFrame(BaseModel):
    """Selects the configured Canonical Tools exposed to this session."""

    model_config = ConfigDict(frozen=True)
    type: Literal["tool_config"] = "tool_config"
    tool_names: list[
        Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{1,63}$")]
    ] = Field(default_factory=list, max_length=64)
    role_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$")


class ConfirmationDecisionFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["confirmation_decision"] = "confirmation_decision"
    confirmation_id: str = Field(min_length=1, max_length=128)
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool


class PlaybackResumeState(BaseModel):
    model_config = ConfigDict(frozen=True)
    generation: int = Field(ge=0)
    played_position_samples: int = Field(ge=0)


class SessionHelloFrame(BaseModel):
    """First frame a client sends on any new physical connection. See
    endpoint_session/registry.py — CONTEXT.md — Endpoint Session.

    ``tenant_id``/``user_id``/``device_id`` are retained only for wire
    compatibility and have no authorization power. v2 identity comes from the
    authenticated physical Transport Adapter.
    """

    model_config = ConfigDict(frozen=True)
    type: Literal["session_hello"] = "session_hello"
    resume_session_id: str | None = None
    resume_token: str | None = None
    protocol_version: int = 1
    supported_protocol_versions: tuple[int, ...] | None = None
    seq: int | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    device_id: str | None = None
    requested_thread_id: str | None = None
    asr_provider: Literal["doubao", "dashscope"] | None = None
    llm_provider: Literal["deepseek", "openai"] | None = None
    previous_voice_session_id: str | None = None
    last_session_sequence: int = Field(default=0, ge=0)
    last_journal_sequence: int = Field(default=0, ge=0)
    playback: PlaybackResumeState | None = None
    heartbeat_interval_ms: int | None = None
    timestamp_ms: int | None = None


class SessionHeartbeatFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["session_heartbeat"] = "session_heartbeat"
    heartbeat_id: int | str | None = None
    timestamp_ms: int | None = None


class SessionPongFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["session_pong"] = "session_pong"
    heartbeat_id: int | str | None = None
    timestamp_ms: int | None = None
    server_timestamp_ms: int


class UserTranscriptFrame(BaseModel):
    """Echoes the client's own ASR-derived transcript back to it, mirroring
    how a client doing its own ASR already sees its UserTextFrame locally
    before sending. The Realtime WebSocket bridge emits this from transcript
    events."""

    model_config = ConfigDict(frozen=True)
    type: Literal["user_transcript"] = "user_transcript"
    text: str
    generation: int | None = None
    is_final: bool = True
    turn_id: str | None = None
    transcript_revision: int | None = Field(default=None, ge=1)


class AssistantTextFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_text"] = "assistant_text"
    text: str
    generation: int
    emotion: str | None = None
    gesture: str | None = None


class AssistantSpeechTextFrame(BaseModel):
    """Cumulative text actually submitted to the speech/TTS path."""

    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_speech_text"] = "assistant_speech_text"
    text: str
    generation: int


class AssistantTextAlignmentFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_text_alignment"] = "assistant_text_alignment"
    generation: int
    speech_id: str
    text: str
    audio_start_us: int = Field(ge=0)
    audio_end_us: int = Field(ge=0)




class AssistantAudioFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_audio"] = "assistant_audio"
    pcm16_base64: str
    sample_rate_hz: int
    generation: int


class AssistantAudioChunkFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_audio_chunk"] = "assistant_audio_chunk"
    pcm16_base64: str
    sample_rate_hz: int
    generation: int
    speech_id: str | None = None
    sequence: int
    is_final: bool


class AssistantSpeechCancelledFrame(BaseModel):
    """Sent the instant τ9 confirms a barge-in: stop playing `generation`'s
    audio and drop whatever is still buffered for it.

    The client must also drop any `assistant_audio_chunk` for this generation
    that arrives *after* this frame. Cancellation takes effect at a chunk
    boundary, so one more chunk can already be in flight — and with the frame
    loop and the turn task both able to call `transport.send` concurrently
    (ADR-0036), their relative wire order isn't guaranteed. That late-chunk
    case is why this frame carries a generation rather than being a bare
    signal. See ADR-0036.
    """

    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_speech_cancelled"] = "assistant_speech_cancelled"
    generation: int
    reason: Literal["interrupted", "failed", "cancelled"] = "interrupted"
    output_epoch: str | None = Field(default=None, min_length=1)
    speech_id: str | None = Field(default=None, min_length=1)
    stop_command_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_stop_identity(self) -> Self:
        fields = (self.output_epoch, self.speech_id, self.stop_command_id)
        if any(value is not None for value in fields) and any(value is None for value in fields):
            raise ValueError("precise stop requires epoch, speech and operation identity")
        return self


class AssistantResponseCompletedFrame(BaseModel):
    """Marks the response boundary independently from its audio segments."""

    model_config = ConfigDict(frozen=True)
    type: Literal["assistant_response_completed"] = "assistant_response_completed"
    generation: int


class SessionAckFrame(BaseModel):
    """Server's reply to SessionHelloFrame, confirming the session id to use
    going forward and whether it was resumed or freshly minted."""

    model_config = ConfigDict(frozen=True)
    type: Literal["session_ack"] = "session_ack"
    session_id: str
    resumed: bool
    output_epoch: str | None = Field(default=None, min_length=1)
    resume_token: str | None = None
    protocol_version: int = 1
    server_time_ms: int | None = None
    heartbeat_interval_ms: int | None = None
    thread_id: str | None = None
    previous_voice_session_id: str | None = None
    error: str | None = None


class SessionCapabilitiesFrame(BaseModel):
    """Advertises live speech/text capabilities after the session handshake."""

    model_config = ConfigDict(frozen=True)
    type: Literal["session_capabilities"] = "session_capabilities"
    server_asr: bool
    server_tts: bool
    assistant_text_streaming: bool = True
    user_transcript_streaming: bool = False
    tts_configurable: bool = False
    tts_preview: bool = False
    protocol_version: int = 1
    heartbeat_interval_ms: int | None = None


class VoiceSessionReadyFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["voice_session_ready"] = "voice_session_ready"
    session_sequence: int = Field(ge=1)
    input_epoch: str = Field(min_length=1)


class VoiceSessionPhaseChangedFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["voice_session_phase_changed"] = "voice_session_phase_changed"
    session_sequence: int = Field(ge=1)
    from_phase: Literal[
        "inactive", "starting", "active", "reconnecting", "stopping", "closed"
    ]
    to_phase: Literal[
        "inactive", "starting", "active", "reconnecting", "stopping", "closed"
    ]


class VoiceSessionSnapshotFrame(BaseModel):
    """Bounded semantic state used when the client's event cursor has a gap."""

    model_config = ConfigDict(frozen=True)
    type: Literal["voice_session_snapshot"] = "voice_session_snapshot"
    session_sequence: int = Field(ge=0)
    journal_sequence: int = Field(ge=0)
    generation: int = Field(ge=0)
    phase: Literal[
        "inactive", "starting", "active", "reconnecting", "stopping", "closed"
    ]
    active_work_refs: tuple[str, ...] = ()
    pending_confirmation_id: str | None = None
    playback_generation: int | None = Field(default=None, ge=0)
    played_position_samples: int | None = Field(default=None, ge=0)


class VoiceSessionEventTailFrame(BaseModel):
    """Contiguous visible lifecycle events after a client resume cursor."""

    model_config = ConfigDict(frozen=True)
    type: Literal["voice_session_event_tail"] = "voice_session_event_tail"
    resume_from_sequence: int = Field(ge=0)
    through_sequence: int = Field(ge=0)
    events: tuple[VoiceSessionPhaseChangedFrame | VoiceSessionReadyFrame, ...] = ()

    @model_validator(mode="after")
    def validate_sequence_boundary(self) -> Self:
        if self.through_sequence < self.resume_from_sequence:
            raise ValueError("Voice Session event tail boundary must not move backward")
        sequences = tuple(event.session_sequence for event in self.events)
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("Voice Session event tail events must be ordered and unique")
        if any(
            sequence <= self.resume_from_sequence or sequence > self.through_sequence
            for sequence in sequences
        ):
            raise ValueError("Voice Session event tail event is outside its boundary")
        return self


class ConfirmationRequestedFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["confirmation_requested"] = "confirmation_requested"
    confirmation_id: str = Field(min_length=1, max_length=128)
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=1000)
    required_channel: Literal["voice", "strong"]
    expires_at: datetime
    generation: int = Field(ge=0)


class ConfirmationResolutionFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["confirmation_resolution"] = "confirmation_resolution"
    confirmation_id: str = Field(min_length=1, max_length=128)
    applied: bool
    approved: bool
    success: bool
    message: str = Field(min_length=1, max_length=1000)
    error: str | None = None


class TtsConfigAckFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["tts_config_ack"] = "tts_config_ack"
    provider: Literal["bailian", "doubao"] = "doubao"
    voice: str
    speech_rate: int
    dialect: Literal[
        "",
        "anhui",
        "cantonese",
        "dongbei",
        "henan",
        "hunan",
        "shaanxi",
        "shandong",
        "sichuan",
    ] = ""
    applied: bool
    error: str | None = None


InboundFrame = (
    InputAudioFrame
    | InputEpochStarted
    | InputCaptureDiagnostic
    | PlaybackProgressV2
    | OutputStopResult
    | UserTextFrame
    | CancelAssistantResponseFrame
    | SessionHelloFrame
    | SessionHeartbeatFrame
    | PlaybackProgressFrame
    | PlaybackQualityFrame
    | ClientConnectionQualityFrame
    | TtsConfigFrame
    | AvatarPersonaConfigFrame
    | ToolConfigFrame
    | ConfirmationDecisionFrame
)
OutboundFrame = (
    AudioGap
    | AssistantTextFrame
    | InputAudioAck
    | AssistantSpeechTextFrame
    | AssistantTextAlignmentFrame
    | AssistantAudioFrame
    | AssistantAudioChunkFrame
    | AssistantResponseCompletedFrame
    | AssistantSpeechCancelledFrame
    | SessionAckFrame
    | SessionPongFrame
    | SessionCapabilitiesFrame
    | TtsConfigAckFrame
    | UserTranscriptFrame
    | VoiceSessionFailureFrame
    | VoiceSessionPhaseChangedFrame
    | VoiceSessionReadyFrame
    | VoiceSessionSnapshotFrame
    | VoiceSessionEventTailFrame
    | ConfirmationRequestedFrame
    | ConfirmationResolutionFrame
)
