"""Resolve the process-owned Cascaded bindings through the Profile seam."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.realtime.profile.models import (
    AudioFormat,
    CapabilityRequirement,
    DataGrant,
    EngineKind,
    FailurePolicy,
    PluginKind,
    PluginManifest,
    PluginPlacement,
    PluginSelection,
    RealtimeProfile,
    RequirementLevel,
    ResolvedRealtimeProfile,
)
from server.realtime.profile.registry import PluginRegistry
from server.realtime.profile.resolver import ProfileResolver
from server.realtime.protocol.audio import AudioEncoding

_VERSION = "1.0.0"
_INPUT_AUDIO = AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltinCascadedBindings:
    vad: object
    asr: object
    turn_manager: object
    brain: object
    speech_renderer: object
    tts: object


def resolve_builtin_profile(
    bindings: BuiltinCascadedBindings,
    *,
    profile_path: str | Path | None = None,
) -> ResolvedRealtimeProfile:
    registry = PluginRegistry()
    selected: list[PluginSelection] = []
    for kind, binding, capability, latency_budget_ms in (
        (PluginKind.VAD, bindings.vad, "voice_activity_detection", 20),
        (PluginKind.ASR, bindings.asr, "streaming_transcription", 300),
        (PluginKind.TURN_MANAGER, bindings.turn_manager, "turn_management", 20),
        (PluginKind.BRAIN, bindings.brain, "streaming_reasoning", 30_000),
        (
            PluginKind.SPEECH_RENDERER,
            bindings.speech_renderer,
            "speech_rendering",
            20,
        ),
        (PluginKind.TTS, bindings.tts, "duplex_speech_synthesis", 10_000),
    ):
        plugin_id = f"builtin.{kind.value}"
        is_input_audio = kind in {PluginKind.VAD, PluginKind.ASR}
        grants = (
            frozenset({DataGrant.INPUT_AUDIO_PROCESSED})
            if is_input_audio
            else frozenset()
        )
        registry.register(
            PluginManifest(
                plugin_id=plugin_id,
                plugin_version=_VERSION,
                plugin_kind=kind,
                contract_version=1,
                placement=PluginPlacement.IN_PROCESS,
                capabilities=frozenset({capability}),
                audio_formats=(_INPUT_AUDIO,) if is_input_audio else (),
                latency_budget_ms=latency_budget_ms,
                approved_data_grants=grants,
                allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
                default_failure_policy=FailurePolicy.FAIL,
            ),
            binding=binding,
        )
        selected.append(
            PluginSelection(
                slot=kind,
                plugin_id=plugin_id,
                plugin_version=_VERSION,
                requested_data_grants=grants,
            )
        )
    profile = (
        _profile_from_payload(
            json.loads(Path(profile_path).read_text(encoding="utf-8"))
        )
        if profile_path is not None
        else RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=tuple(selected),
        )
    )
    return ProfileResolver(registry).resolve(profile)


def _profile_from_payload(payload: Any) -> RealtimeProfile:
    if not isinstance(payload, dict):
        raise TypeError("Realtime Profile file must contain a JSON object")
    raw_plugins = payload.get("plugins")
    if not isinstance(raw_plugins, list):
        raise TypeError("Realtime Profile plugins must be a JSON array")
    plugins: list[PluginSelection] = []
    for raw in raw_plugins:
        if not isinstance(raw, dict):
            raise TypeError("Realtime Profile plugin selection must be an object")
        raw_grants = raw.get("requested_data_grants", [])
        if not isinstance(raw_grants, list):
            raise TypeError("requested_data_grants must be an array")
        raw_config = raw.get("config", {})
        if not isinstance(raw_config, dict):
            raise TypeError("plugin config must be an object")
        raw_failure_policy = raw.get("failure_policy")
        plugins.append(
            PluginSelection(
                slot=PluginKind(str(raw["slot"])),
                plugin_id=str(raw["plugin_id"]),
                plugin_version=str(raw["plugin_version"]),
                requested_data_grants=frozenset(
                    DataGrant(str(value)) for value in raw_grants
                ),
                failure_policy=(
                    FailurePolicy(str(raw_failure_policy))
                    if raw_failure_policy is not None
                    else None
                ),
                config=raw_config,
            )
        )
    raw_requirements = payload.get("requirements", [])
    if not isinstance(raw_requirements, list):
        raise TypeError("Realtime Profile requirements must be a JSON array")
    requirements = []
    for raw in raw_requirements:
        if not isinstance(raw, dict):
            raise TypeError("Realtime Profile requirement must be an object")
        requirements.append(
            CapabilityRequirement(
                capability=str(raw["capability"]),
                level=RequirementLevel(str(raw["level"])),
            )
        )
    return RealtimeProfile(
        schema_version=int(payload.get("schema_version", 1)),
        engine_kind=EngineKind(str(payload.get("engine_kind", "cascaded"))),
        plugins=tuple(plugins),
        requirements=tuple(requirements),
    )
