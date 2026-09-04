"""Versioned Endpoint wire contract owned by the Voice Session Runtime."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProtocolIncompatible(Exception):
    """Raised when client and server have no explicitly shared protocol version."""


class CaptureMode(StrEnum):
    PREBUFFER = "prebuffer"
    LIVE = "live"


class AudioFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    format_id: str = Field(min_length=1)
    encoding: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate_hz: int = Field(default=16_000, gt=0)
    channels: int = Field(default=1, ge=1, le=2)


class DeviceCaptureProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_version: int = Field(default=1, ge=1)
    max_buffer_ms: int = Field(default=30_000, gt=0)
    silence_threshold: float = Field(default=0.003, ge=0, le=1)
    pre_roll_ms: int = Field(default=100, ge=0)
    frame_duration_ms: int = Field(default=32, gt=0)
    max_replay_rate: float = Field(default=2.0, ge=1, le=2)
    catchup_deadline_ms: int = Field(default=30_000, gt=0)
    queue_low_watermark: int = Field(default=8, ge=0)
    queue_high_watermark: int = Field(default=32, gt=0)

    @model_validator(mode="after")
    def validate_watermarks(self) -> DeviceCaptureProfile:
        if self.queue_low_watermark >= self.queue_high_watermark:
            raise ValueError("queue low watermark must be lower than high watermark")
        return self


class DeviceCaptureConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    echo_cancellation: bool | None = None
    noise_suppression: bool | None = None
    auto_gain_control: bool | None = None


class DeviceCaptureEffectOwners(BaseModel):
    model_config = ConfigDict(frozen=True)

    echo_cancellation: Literal["device", "none"] = "none"
    noise_suppression: Literal["device", "none"] = "none"
    auto_gain_control: Literal["device", "none"] = "none"


class InputEpochStarted(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["input_epoch_started"] = "input_epoch_started"
    input_epoch: str = Field(min_length=1)
    format: AudioFormat
    requested_profile: DeviceCaptureProfile
    effective_profile: DeviceCaptureProfile
    timeline_origin_ms: float = Field(default=0, ge=0)
    requested_constraints: DeviceCaptureConstraints = Field(
        default_factory=DeviceCaptureConstraints
    )
    effective_constraints: DeviceCaptureConstraints = Field(
        default_factory=DeviceCaptureConstraints
    )
    effect_owners: DeviceCaptureEffectOwners = Field(
        default_factory=DeviceCaptureEffectOwners
    )


class InputAudioFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["input_audio_frame"] = "input_audio_frame"
    input_epoch: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    start_sample: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    capture_mode: CaptureMode
    pcm16_base64: str = Field(min_length=1)


class InputAudioAck(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["input_audio_ack"] = "input_audio_ack"
    input_epoch: str = Field(min_length=1)
    highest_contiguous_sequence: int = Field(ge=0)
    next_start_sample: int = Field(ge=0)


class InputCaptureDiagnostic(BaseModel):
    """Content-free client evidence for a failed capture epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["input_capture_diagnostic"] = "input_capture_diagnostic"
    input_epoch: str = Field(min_length=1)
    outcome: Literal["overflow", "catchup_deadline", "audio_gap", "worklet_failure"]
    buffered_frames: int = Field(default=0, ge=0)
    buffered_duration_ms: int = Field(default=0, ge=0)
    aggregate_energy: float = Field(default=0, ge=0, le=1)


class AudioGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["audio_gap"] = "audio_gap"
    input_epoch: str = Field(min_length=1)
    expected_sequence: int = Field(ge=0)
    received_sequence: int = Field(ge=0)
    expected_start_sample: int = Field(ge=0)
    received_start_sample: int = Field(ge=0)


class PlaybackProgressV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["playback_progress_v2"] = "playback_progress_v2"
    output_epoch: str = Field(min_length=1)
    speech_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    phase: Literal["started", "stopped", "finished"]
    played_position_samples: int = Field(ge=0)


class VoiceSessionFailureFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["voice_session_failed"] = "voice_session_failed"
    error_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    code: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)
    session_disposition: Literal[
        "keep_reconnecting", "close", "continuation_required"
    ]
    safe_message: str = Field(min_length=1)


class InputEpochTimeline:
    """Validate ordered frame/sample continuity for the one active input epoch."""

    def __init__(self) -> None:
        self._epoch: InputEpochStarted | None = None
        self._next_sequence = 0
        self._next_start_sample = 0

    def start(self, epoch: InputEpochStarted) -> None:
        self._epoch = epoch
        self._next_sequence = 0
        self._next_start_sample = 0

    def accept(self, frame: InputAudioFrame) -> InputAudioAck | AudioGap | None:
        if self._epoch is None or frame.input_epoch != self._epoch.input_epoch:
            raise ValueError("input audio frame does not belong to the active epoch")
        if frame.sequence < self._next_sequence:
            return None
        if (
            frame.sequence != self._next_sequence
            or frame.start_sample != self._next_start_sample
        ):
            return AudioGap(
                input_epoch=frame.input_epoch,
                expected_sequence=self._next_sequence,
                received_sequence=frame.sequence,
                expected_start_sample=self._next_start_sample,
                received_start_sample=frame.start_sample,
            )
        self._next_sequence += 1
        self._next_start_sample += frame.sample_count
        return InputAudioAck(
            input_epoch=frame.input_epoch,
            highest_contiguous_sequence=frame.sequence,
            next_start_sample=self._next_start_sample,
        )


class SessionHello(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["session_hello"] = "session_hello"
    supported_protocol_versions: tuple[int, ...] = Field(min_length=1)
    requested_thread_id: str | None = None
    resume_session_id: str | None = None
    resume_token: str | None = None
    last_session_sequence: int = Field(default=0, ge=0)
    last_journal_sequence: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_versions(self) -> SessionHello:
        if any(version < 1 for version in self.supported_protocol_versions):
            raise ValueError("protocol versions must be positive")
        if len(set(self.supported_protocol_versions)) != len(
            self.supported_protocol_versions
        ):
            raise ValueError("protocol versions must be unique")
        return self

    def negotiate(self, *, server_supported_versions: tuple[int, ...]) -> int:
        client_versions = set(self.supported_protocol_versions)
        for version in server_supported_versions:
            if version in client_versions:
                return version
        raise ProtocolIncompatible("client and server have no shared protocol version")
