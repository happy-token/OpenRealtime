"""Validate and freeze Realtime Profiles before media starts."""

from __future__ import annotations

import hashlib
import json

from server.realtime.profile.models import (
    AudioFormat,
    DataGrant,
    FailurePolicy,
    PluginKind,
    RealtimeProfile,
    RequirementLevel,
    ResolvedPlugin,
    ResolvedRealtimeProfile,
)
from server.realtime.profile.registry import PluginRegistry

_INPUT_AUDIO_SLOTS = frozenset(
    {
        PluginKind.VAD,
        PluginKind.ASR,
        PluginKind.AUDIO_PROCESSOR,
        PluginKind.AUDIO_ANALYZER,
        PluginKind.AUDIO_SINK,
    }
)
_AUDIO_DATA_GRANTS = frozenset({DataGrant.INPUT_AUDIO_RAW, DataGrant.INPUT_AUDIO_PROCESSED})


class ProfileResolutionError(ValueError):
    pass


class ProfileResolver:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def resolve(self, profile: RealtimeProfile) -> ResolvedRealtimeProfile:
        if profile.schema_version != 1:
            raise ProfileResolutionError(
                f"unsupported realtime profile schema version {profile.schema_version}"
            )
        resolved_plugins: list[ResolvedPlugin] = []
        available_capabilities: set[str] = set()
        audio_format_sets: list[set[AudioFormat]] = []
        for selection in profile.plugins:
            registered = self._registry.resolve(
                selection.plugin_id,
                selection.plugin_version,
            )
            manifest = registered.manifest
            if manifest.plugin_kind is not selection.slot:
                raise ProfileResolutionError(
                    f"plugin {manifest.plugin_id}@{manifest.plugin_version} has kind "
                    f"{manifest.plugin_kind.value}, not {selection.slot.value}"
                )
            if not selection.requested_data_grants <= manifest.approved_data_grants:
                unapproved = selection.requested_data_grants - manifest.approved_data_grants
                raise ProfileResolutionError(
                    "profile requested unapproved data grants: "
                    + ", ".join(sorted(grant.value for grant in unapproved))
                )
            if (
                selection.slot in _INPUT_AUDIO_SLOTS
                and not selection.requested_data_grants.intersection(_AUDIO_DATA_GRANTS)
            ):
                raise ProfileResolutionError(
                    f"audio plugin {manifest.plugin_id} must receive an explicit audio data grant"
                )
            failure_policy = selection.failure_policy or manifest.default_failure_policy
            if failure_policy not in manifest.allowed_failure_policies:
                raise ProfileResolutionError(
                    f"failure policy {failure_policy.value} is not allowed for "
                    f"{manifest.plugin_id}@{manifest.plugin_version}"
                )
            if failure_policy is FailurePolicy.BYPASS and not manifest.bypass_safe:
                raise ProfileResolutionError("only bypass-safe plugins may use BYPASS")
            if (
                selection.slot is PluginKind.AUDIO_PROCESSOR
                and failure_policy is FailurePolicy.DEGRADE
            ):
                raise ProfileResolutionError(
                    "audio processors must use BYPASS, not DEGRADE, to continue after failure"
                )
            if selection.slot is PluginKind.TURN_MANAGER and failure_policy in {
                FailurePolicy.BYPASS,
                FailurePolicy.DEGRADE,
            }:
                raise ProfileResolutionError("Turn Manager cannot be bypassed or degraded")
            _validate_config(selection.config, manifest.config_schema.value)
            resolved_plugins.append(
                ResolvedPlugin(
                    selection=selection,
                    manifest=manifest,
                    binding=registered.binding,
                    effective_data_grants=selection.requested_data_grants,
                    failure_policy=failure_policy,
                )
            )
            available_capabilities.update(manifest.capabilities)
            if selection.slot in _INPUT_AUDIO_SLOTS and manifest.audio_formats:
                audio_format_sets.append(set(manifest.audio_formats))

        degraded: list[str] = []
        for requirement in profile.requirements:
            if requirement.capability in available_capabilities:
                continue
            if requirement.level is RequirementLevel.REQUIRED:
                raise ProfileResolutionError(
                    f"required capability {requirement.capability!r} is unavailable"
                )
            if requirement.level is RequirementLevel.PREFERRED:
                degraded.append(requirement.capability)

        negotiated_input_format = _negotiate_input_format(audio_format_sets)
        digest = _diagnostic_digest(
            profile=profile,
            plugins=resolved_plugins,
            negotiated_input_format=negotiated_input_format,
            degraded=degraded,
        )
        return ResolvedRealtimeProfile(
            schema_version=profile.schema_version,
            engine_kind=profile.engine_kind,
            plugins=tuple(resolved_plugins),
            negotiated_input_format=negotiated_input_format,
            degraded_capabilities=tuple(sorted(degraded)),
            diagnostic_digest=digest,
        )


def _negotiate_input_format(format_sets: list[set[AudioFormat]]) -> AudioFormat | None:
    if not format_sets:
        return None
    common = set.intersection(*format_sets)
    if not common:
        raise ProfileResolutionError("selected input audio plugins have no common format")
    return min(
        common,
        key=lambda value: (
            value.encoding.value,
            -value.sample_rate_hz,
            value.channels,
        ),
    )


def _validate_config(config: dict[str, object], schema: dict[str, object]) -> None:
    if not schema:
        return
    if schema.get("type") != "object":
        raise ProfileResolutionError("plugin config schema root must have type 'object'")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ProfileResolutionError("plugin config schema properties must be an object")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        raise ProfileResolutionError("plugin config schema required must be a string list")
    for name in required:
        if name not in config:
            raise ProfileResolutionError(f"required config field {name!r} is missing")
    if schema.get("additionalProperties", True) is False:
        unknown = set(config) - set(properties)
        if unknown:
            raise ProfileResolutionError(
                "unknown plugin config fields: " + ", ".join(sorted(unknown))
            )
    for name, value in config.items():
        field_schema = properties.get(name)
        if field_schema is None:
            continue
        if not isinstance(field_schema, dict):
            raise ProfileResolutionError(f"config schema field {name!r} must be an object")
        _validate_config_value(name, value, field_schema)


def _validate_config_value(name: str, value: object, schema: dict[str, object]) -> None:
    expected = schema.get("type")
    valid = {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }
    if isinstance(expected, str) and expected in valid and not valid[expected]:
        raise ProfileResolutionError(f"config field {name!r} must have type {expected}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise ProfileResolutionError(f"config field {name!r} is not an allowed value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ProfileResolutionError(f"config field {name!r} must be >= {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ProfileResolutionError(f"config field {name!r} must be <= {maximum}")


def _diagnostic_digest(
    *,
    profile: RealtimeProfile,
    plugins: list[ResolvedPlugin],
    negotiated_input_format: AudioFormat | None,
    degraded: list[str],
) -> str:
    payload = {
        "schema_version": profile.schema_version,
        "engine_kind": profile.engine_kind.value,
        "plugins": [
            {
                "slot": plugin.selection.slot.value,
                "plugin_id": plugin.manifest.plugin_id,
                "plugin_version": plugin.manifest.plugin_version,
                "contract_version": plugin.manifest.contract_version,
                "config": plugin.selection.config,
                "data_grants": sorted(grant.value for grant in plugin.effective_data_grants),
                "failure_policy": plugin.failure_policy.value,
            }
            for plugin in plugins
        ],
        "negotiated_input_format": (
            negotiated_input_format.to_payload() if negotiated_input_format is not None else None
        ),
        "requirements": sorted(
            (
                {
                    "capability": requirement.capability,
                    "level": requirement.level.value,
                }
                for requirement in profile.requirements
            ),
            key=lambda value: (value["capability"], value["level"]),
        ),
        "degraded_capabilities": sorted(degraded),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
