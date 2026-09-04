from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime import ProfileFailureRecovery, RealtimeCapabilityFailed
from server.realtime.profile import (
    DataGrant,
    EngineKind,
    FailurePolicy,
    PluginKind,
    PluginManifest,
    PluginPlacement,
    PluginSelection,
    ResolvedPlugin,
    ResolvedRealtimeProfile,
)


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


def profile(policy: FailurePolicy) -> ResolvedRealtimeProfile:
    selection = PluginSelection(
        slot=PluginKind.ASR,
        plugin_id="test.asr",
        plugin_version="1.0.0",
        failure_policy=policy,
    )
    manifest = PluginManifest(
        plugin_id="test.asr",
        plugin_version="1.0.0",
        plugin_kind=PluginKind.ASR,
        contract_version=1,
        placement=PluginPlacement.IN_PROCESS,
        capabilities=frozenset({"asr"}),
        audio_formats=(),
        latency_budget_ms=100,
        approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
        allowed_failure_policies=frozenset({policy}),
        default_failure_policy=policy,
    )
    return ResolvedRealtimeProfile(
        schema_version=1,
        engine_kind=EngineKind.CASCADED,
        plugins=(
            ResolvedPlugin(
                selection=selection,
                manifest=manifest,
                binding=object(),
                effective_data_grants=frozenset(),
                failure_policy=policy,
            ),
        ),
        negotiated_input_format=None,
        degraded_capabilities=(),
        diagnostic_digest="a" * 64,
    )


def failure() -> RealtimeCapabilityFailed:
    return RealtimeCapabilityFailed(
        event_id="failure-1",
        context=context(),
        conversation_sequence=1,
        occurred_at=datetime.now(UTC),
        capability="asr",
        error="connection lost",
    )


async def test_restart_same_returns_the_current_resolved_profile() -> None:
    current = profile(FailurePolicy.RESTART_SAME)

    recovered = await ProfileFailureRecovery().recovery_profile(
        current_profile=current,
        event=failure(),
    )

    assert recovered is current


class RecordingFallbackResolver:
    def __init__(self, fallback: object) -> None:
        self.fallback = fallback
        self.failed_plugin: ResolvedPlugin | None = None

    async def resolve_fallback(self, *, current_profile, failed_plugin, event):
        del current_profile, event
        self.failed_plugin = failed_plugin
        return self.fallback


async def test_migrate_policy_resolves_an_explicit_fallback_profile() -> None:
    current = profile(FailurePolicy.MIGRATE_TO_FALLBACK)
    fallback = profile(FailurePolicy.FAIL)
    resolver = RecordingFallbackResolver(fallback)

    recovered = await ProfileFailureRecovery(
        fallback_resolver=resolver,
    ).recovery_profile(
        current_profile=current,
        event=failure(),
    )

    assert recovered is fallback
    assert resolver.failed_plugin is current.plugins[0]


async def test_migrate_policy_without_fallback_is_an_explicit_failure() -> None:
    current = profile(FailurePolicy.MIGRATE_TO_FALLBACK)

    with pytest.raises(RuntimeError, match="requires a fallback profile"):
        await ProfileFailureRecovery().recovery_profile(
            current_profile=current,
            event=failure(),
        )
