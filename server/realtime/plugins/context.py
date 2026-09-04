"""Minimized identity and grants exposed to one audio plugin."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from server.core.interaction_context import InteractionContext
from server.realtime.profile import DataGrant, ResolvedPlugin


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityContext:
    plugin_id: str
    plugin_version: str
    voice_session_id: str
    effective_data_grants: frozenset[DataGrant]
    tenant_pseudonymous_id: str | None = None


def capability_context_for(
    plugin: ResolvedPlugin,
    *,
    interaction_context: InteractionContext,
    pseudonymization_key: str,
) -> CapabilityContext:
    if not pseudonymization_key:
        raise ValueError("pseudonymization key must be non-empty")
    tenant_pseudonym = None
    if DataGrant.TENANT_PSEUDONYMOUS_ID in plugin.effective_data_grants:
        tenant_pseudonym = hmac.new(
            pseudonymization_key.encode(),
            interaction_context.tenant_id.encode(),
            hashlib.sha256,
        ).hexdigest()
    return CapabilityContext(
        plugin_id=plugin.manifest.plugin_id,
        plugin_version=plugin.manifest.plugin_version,
        voice_session_id=interaction_context.voice_session_id,
        effective_data_grants=plugin.effective_data_grants,
        tenant_pseudonymous_id=tenant_pseudonym,
    )
