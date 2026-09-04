"""Failure-policy routing for managed Realtime Conversation recovery."""

from __future__ import annotations

from typing import Protocol

from server.realtime.profile import (
    FailurePolicy,
    ResolvedPlugin,
    ResolvedRealtimeProfile,
)
from server.realtime.protocol.events import RealtimeCapabilityFailed


class FallbackProfileResolver(Protocol):
    async def resolve_fallback(
        self,
        *,
        current_profile: ResolvedRealtimeProfile,
        failed_plugin: ResolvedPlugin,
        event: RealtimeCapabilityFailed,
    ) -> object: ...


class RealtimeFailureRecovery(Protocol):
    async def recovery_profile(
        self,
        *,
        current_profile: object,
        event: RealtimeCapabilityFailed,
    ) -> object | None: ...


class ProfileFailureRecovery:
    """Interpret resolved plugin failure policies at the conversation seam."""

    def __init__(
        self,
        *,
        fallback_resolver: FallbackProfileResolver | None = None,
    ) -> None:
        self._fallback_resolver = fallback_resolver

    async def recovery_profile(
        self,
        *,
        current_profile: object,
        event: RealtimeCapabilityFailed,
    ) -> object | None:
        if not isinstance(current_profile, ResolvedRealtimeProfile):
            return None
        plugin = _failed_plugin(current_profile, event.capability)
        if plugin is None:
            return None
        if plugin.failure_policy is FailurePolicy.RESTART_SAME:
            return current_profile
        if plugin.failure_policy is not FailurePolicy.MIGRATE_TO_FALLBACK:
            return None
        if self._fallback_resolver is None:
            raise RuntimeError(
                f"plugin {plugin.selection.plugin_id!r} requires a fallback profile"
            )
        return await self._fallback_resolver.resolve_fallback(
            current_profile=current_profile,
            failed_plugin=plugin,
            event=event,
        )


def _failed_plugin(
    profile: ResolvedRealtimeProfile,
    capability: str,
) -> ResolvedPlugin | None:
    exact = next(
        (
            plugin
            for plugin in profile.plugins
            if plugin.selection.slot.value == capability
        ),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (
            plugin
            for plugin in profile.plugins
            if capability in plugin.manifest.capabilities
        ),
        None,
    )
