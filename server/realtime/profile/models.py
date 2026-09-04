"""Immutable manifests, user selections, and resolved Realtime Profiles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from server.realtime.protocol.audio import AudioEncoding


class EngineKind(StrEnum):
    CASCADED = "cascaded"
    NATIVE = "native"


class PluginKind(StrEnum):
    ENGINE = "engine"
    VAD = "vad"
    ASR = "asr"
    TURN_MANAGER = "turn_manager"
    BRAIN = "brain"
    SPEECH_RENDERER = "speech_renderer"
    TTS = "tts"
    AUDIO_PROCESSOR = "audio_processor"
    AUDIO_ANALYZER = "audio_analyzer"
    AUDIO_SINK = "audio_sink"


class PluginPlacement(StrEnum):
    IN_PROCESS = "in_process"
    SIDECAR = "sidecar"
    REMOTE = "remote"


class DataGrant(StrEnum):
    INPUT_AUDIO_PROCESSED = "input_audio_processed"
    INPUT_AUDIO_RAW = "input_audio_raw"
    PLAYBACK_REFERENCE_AUDIO = "playback_reference_audio"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    SPEAKER_PROFILE_REFERENCE = "speaker_profile_reference"
    TENANT_PSEUDONYMOUS_ID = "tenant_pseudonymous_id"
    ARTIFACT_WRITE = "artifact_write"
    NETWORK_EGRESS = "network_egress"


class FailurePolicy(StrEnum):
    FAIL = "fail"
    RESTART_SAME = "restart_same"
    BYPASS = "bypass"
    MIGRATE_TO_FALLBACK = "migrate_to_fallback"
    DEGRADE = "degrade"


class RequirementLevel(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class AudioFormat:
    encoding: AudioEncoding
    sample_rate_hz: int
    channels: int

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0 or self.channels <= 0:
            raise ValueError("audio format sample rate and channels must be positive")

    def to_payload(self) -> dict[str, str | int]:
        return {
            "encoding": self.encoding.value,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
        }


@dataclass(frozen=True, slots=True, init=False)
class PluginConfigSchema:
    canonical_json: str

    def __init__(self, value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping):
            raise TypeError("plugin config schema must be an object")
        try:
            canonical = json.dumps(
                dict(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("plugin config schema must be JSON serializable") from error
        object.__setattr__(self, "canonical_json", canonical)

    @property
    def value(self) -> dict[str, Any]:
        decoded = json.loads(self.canonical_json)
        assert isinstance(decoded, dict)
        return decoded


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginManifest:
    plugin_id: str
    plugin_version: str
    plugin_kind: PluginKind
    contract_version: int
    placement: PluginPlacement
    capabilities: frozenset[str]
    audio_formats: tuple[AudioFormat, ...]
    latency_budget_ms: int
    approved_data_grants: frozenset[DataGrant]
    allowed_failure_policies: frozenset[FailurePolicy]
    default_failure_policy: FailurePolicy
    bypass_safe: bool = False
    config_schema: PluginConfigSchema = field(default_factory=lambda: PluginConfigSchema({}))
    data_classification: str | None = None
    retention_days: int | None = None

    def __post_init__(self) -> None:
        if not self.plugin_id or not self.plugin_version:
            raise ValueError("plugin identity and version must be non-empty")
        if self.contract_version < 1 or self.latency_budget_ms <= 0:
            raise ValueError("contract version and latency budget must be positive")
        if not self.capabilities:
            raise ValueError("plugin capabilities must be non-empty")
        if not self.allowed_failure_policies:
            raise ValueError("plugin failure policies must be non-empty")
        if self.default_failure_policy not in self.allowed_failure_policies:
            raise ValueError("default failure policy must be allowed by the manifest")
        if FailurePolicy.BYPASS in self.allowed_failure_policies and not self.bypass_safe:
            raise ValueError("BYPASS may only be advertised by a bypass-safe plugin")
        if "audio_recording" in self.capabilities:
            if not self.data_classification or self.retention_days is None:
                raise ValueError(
                    "audio recording plugins must declare data classification and retention"
                )
            if self.retention_days < 1:
                raise ValueError("audio recording retention_days must be positive")


@dataclass(frozen=True, slots=True, init=False)
class PluginSelection:
    slot: PluginKind
    plugin_id: str
    plugin_version: str
    requested_data_grants: frozenset[DataGrant]
    failure_policy: FailurePolicy | None
    config_json: str

    def __init__(
        self,
        *,
        slot: PluginKind,
        plugin_id: str,
        plugin_version: str,
        requested_data_grants: frozenset[DataGrant] = frozenset(),
        failure_policy: FailurePolicy | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        if not plugin_id or not plugin_version:
            raise ValueError("selected plugin identity and version must be non-empty")
        try:
            config_json = json.dumps(
                dict(config or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("plugin config must be JSON serializable") from error
        object.__setattr__(self, "slot", slot)
        object.__setattr__(self, "plugin_id", plugin_id)
        object.__setattr__(self, "plugin_version", plugin_version)
        object.__setattr__(self, "requested_data_grants", requested_data_grants)
        object.__setattr__(self, "failure_policy", failure_policy)
        object.__setattr__(self, "config_json", config_json)

    @property
    def config(self) -> dict[str, Any]:
        value = json.loads(self.config_json)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityRequirement:
    capability: str
    level: RequirementLevel

    def __post_init__(self) -> None:
        if not self.capability:
            raise ValueError("required capability name must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class RealtimeProfile:
    schema_version: int
    engine_kind: EngineKind
    plugins: tuple[PluginSelection, ...]
    requirements: tuple[CapabilityRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("profile schema version must be positive")
        if not self.plugins:
            raise ValueError("realtime profile must select at least one plugin")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedPlugin:
    selection: PluginSelection
    manifest: PluginManifest
    binding: object
    effective_data_grants: frozenset[DataGrant]
    failure_policy: FailurePolicy


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRealtimeProfile:
    schema_version: int
    engine_kind: EngineKind
    plugins: tuple[ResolvedPlugin, ...]
    negotiated_input_format: AudioFormat | None
    degraded_capabilities: tuple[str, ...]
    diagnostic_digest: str
