from __future__ import annotations

import pytest

from server.realtime import AudioEncoding
from server.realtime.profile import (
    AudioFormat,
    CapabilityRequirement,
    DataGrant,
    EngineKind,
    FailurePolicy,
    PluginConfigSchema,
    PluginKind,
    PluginManifest,
    PluginPlacement,
    PluginRegistry,
    PluginSelection,
    ProfileResolutionError,
    ProfileResolver,
    RealtimeProfile,
    RequirementLevel,
)


def test_profile_resolves_exact_plugins_grants_format_and_stable_digest() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="custom.voiceprint",
        plugin_version="2.1.0",
        plugin_kind=PluginKind.AUDIO_ANALYZER,
        contract_version=1,
        placement=PluginPlacement.SIDECAR,
        capabilities=frozenset({"speaker_evidence"}),
        audio_formats=(
            AudioFormat(
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=16_000,
                channels=1,
            ),
        ),
        latency_budget_ms=80,
        approved_data_grants=frozenset(
            {DataGrant.INPUT_AUDIO_PROCESSED, DataGrant.SPEAKER_PROFILE_REFERENCE}
        ),
        allowed_failure_policies=frozenset({FailurePolicy.DEGRADE, FailurePolicy.FAIL}),
        default_failure_policy=FailurePolicy.DEGRADE,
    )
    registry.register(manifest, binding=object())
    profile = RealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=(
            PluginSelection(
                slot=PluginKind.AUDIO_ANALYZER,
                plugin_id="custom.voiceprint",
                plugin_version="2.1.0",
                requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            ),
        ),
        requirements=(
            CapabilityRequirement(
                capability="speaker_evidence",
                level=RequirementLevel.REQUIRED,
            ),
        ),
    )

    first = ProfileResolver(registry).resolve(profile)
    second = ProfileResolver(registry).resolve(profile)

    assert first.plugins[0].manifest is manifest
    assert first.plugins[0].effective_data_grants == frozenset({DataGrant.INPUT_AUDIO_PROCESSED})
    assert first.negotiated_input_format == AudioFormat(
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate_hz=16_000,
        channels=1,
    )
    assert first.degraded_capabilities == ()
    assert len(first.diagnostic_digest) == 64
    assert first.diagnostic_digest == second.diagnostic_digest


def test_profile_cannot_expand_registry_approved_data_grants() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginManifest(
            plugin_id="custom.voiceprint",
            plugin_version="2.1.0",
            plugin_kind=PluginKind.AUDIO_ANALYZER,
            contract_version=1,
            placement=PluginPlacement.SIDECAR,
            capabilities=frozenset({"speaker_evidence"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=80,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
            default_failure_policy=FailurePolicy.DEGRADE,
        ),
        binding=object(),
    )
    profile = RealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=(
            PluginSelection(
                slot=PluginKind.AUDIO_ANALYZER,
                plugin_id="custom.voiceprint",
                plugin_version="2.1.0",
                requested_data_grants=frozenset(
                    {DataGrant.INPUT_AUDIO_PROCESSED, DataGrant.INPUT_AUDIO_RAW}
                ),
            ),
        ),
    )

    with pytest.raises(
        ProfileResolutionError,
        match="unapproved data grants: input_audio_raw",
    ):
        ProfileResolver(registry).resolve(profile)


def test_profile_rejects_plugin_config_outside_manifest_schema() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginManifest(
            plugin_id="builtin.noise_suppression",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_PROCESSOR,
            contract_version=1,
            placement=PluginPlacement.IN_PROCESS,
            capabilities=frozenset({"noise_suppression"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=10,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
            allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
            default_failure_policy=FailurePolicy.FAIL,
            config_schema=PluginConfigSchema(
                {
                    "type": "object",
                    "properties": {
                        "strength": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        }
                    },
                    "required": ["strength"],
                    "additionalProperties": False,
                }
            ),
        ),
        binding=object(),
    )
    profile = RealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=(
            PluginSelection(
                slot=PluginKind.AUDIO_PROCESSOR,
                plugin_id="builtin.noise_suppression",
                plugin_version="1.0.0",
                requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                config={"strength": 1.5},
            ),
        ),
    )

    with pytest.raises(
        ProfileResolutionError,
        match="config field 'strength' must be <= 1",
    ):
        ProfileResolver(registry).resolve(profile)


def test_required_capability_blocks_start_while_preferred_degrades_explicitly() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="custom.voiceprint",
        plugin_version="2.1.0",
        plugin_kind=PluginKind.AUDIO_ANALYZER,
        contract_version=1,
        placement=PluginPlacement.SIDECAR,
        capabilities=frozenset({"speaker_evidence"}),
        audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
        latency_budget_ms=80,
        approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
        allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
        default_failure_policy=FailurePolicy.DEGRADE,
    )
    registry.register(manifest, binding=object())

    preferred = RealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=(
            PluginSelection(
                slot=PluginKind.AUDIO_ANALYZER,
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.plugin_version,
                requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            ),
        ),
        requirements=(
            CapabilityRequirement(
                capability="server_input_audio_tap",
                level=RequirementLevel.PREFERRED,
            ),
        ),
    )
    assert ProfileResolver(registry).resolve(preferred).degraded_capabilities == (
        "server_input_audio_tap",
    )

    required = RealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=preferred.plugins,
        requirements=(
            CapabilityRequirement(
                capability="server_input_audio_tap",
                level=RequirementLevel.REQUIRED,
            ),
        ),
    )
    with pytest.raises(
        ProfileResolutionError,
        match="required capability 'server_input_audio_tap' is unavailable",
    ):
        ProfileResolver(registry).resolve(required)


def test_diagnostic_digest_changes_when_requirement_contract_changes() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="custom.voiceprint",
        plugin_version="2.1.0",
        plugin_kind=PluginKind.AUDIO_ANALYZER,
        contract_version=1,
        placement=PluginPlacement.SIDECAR,
        capabilities=frozenset({"speaker_evidence"}),
        audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
        latency_budget_ms=80,
        approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
        allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
        default_failure_policy=FailurePolicy.DEGRADE,
    )
    registry.register(manifest, binding=object())
    selection = PluginSelection(
        slot=PluginKind.AUDIO_ANALYZER,
        plugin_id=manifest.plugin_id,
        plugin_version=manifest.plugin_version,
        requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
    )
    resolver = ProfileResolver(registry)
    without_requirement = resolver.resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(selection,),
        )
    )
    with_requirement = resolver.resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(selection,),
            requirements=(
                CapabilityRequirement(
                    capability="speaker_evidence",
                    level=RequirementLevel.REQUIRED,
                ),
            ),
        )
    )

    assert without_requirement.diagnostic_digest != with_requirement.diagnostic_digest
