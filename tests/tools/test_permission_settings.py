from __future__ import annotations

import asyncio
import json

import pytest

from server.tools.canonical import ConfirmationRequirement, LatencyClass, RiskLevel, ToolEffect
from server.tools.permission_settings import ToolPermissionMode, tool_permission_mode
from server.tools.policy_gateway import (
    Allow,
    DefaultToolPolicyGateway,
    Deny,
    GrantRejected,
    RequireConfirmation,
    ToolExecutor,
    ToolPolicyContext,
)
from tests.tools.test_policy_gateway import registry, request


def write_settings(root, mode="full", overrides=None):
    (root / "settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "records": [
                    {
                        "owner_id": "user-1",
                        "mode": mode,
                        "role_overrides": overrides or {},
                        "updated_at": "2026-10-01T00:00:00Z",
                    }
                ],
            }
        )
    )


def test_default_is_full_and_settings_are_owner_and_role_scoped(tmp_path):
    assert tool_permission_mode("user-1", root=tmp_path) is ToolPermissionMode.FULL
    write_settings(tmp_path, "balanced", {"role-a": "confirm"})
    assert tool_permission_mode("user-1", root=tmp_path) is ToolPermissionMode.BALANCED
    assert tool_permission_mode("user-1", "role-a", root=tmp_path) is ToolPermissionMode.CONFIRM
    assert tool_permission_mode("user-1", "role-b", root=tmp_path) is ToolPermissionMode.BALANCED
    assert tool_permission_mode("user-2", "role-a", root=tmp_path) is ToolPermissionMode.FULL


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        '{"version":1,"records":[null]}',
        '{"version":1,"records":[{"owner_id":"user-1","mode":"other"}]}',
    ],
)
def test_corrupt_settings_require_confirmation(tmp_path, payload):
    (tmp_path / "settings.json").write_text(payload)
    assert tool_permission_mode("user-1", root=tmp_path) is ToolPermissionMode.CONFIRM


async def handler(arguments):
    return "ok"


@pytest.mark.parametrize(
    "mode,effect,risk,expected",
    [
        (ToolPermissionMode.FULL, ToolEffect.READ_SENSITIVE, RiskLevel.MEDIUM, Allow),
        (ToolPermissionMode.FULL, ToolEffect.COMMUNICATE_EXTERNAL, RiskLevel.HIGH, Allow),
        (ToolPermissionMode.BALANCED, ToolEffect.READ_SENSITIVE, RiskLevel.MEDIUM, Allow),
        (
            ToolPermissionMode.BALANCED,
            ToolEffect.WRITE_REVERSIBLE,
            RiskLevel.LOW,
            RequireConfirmation,
        ),
        (
            ToolPermissionMode.BALANCED,
            ToolEffect.COMMUNICATE_EXTERNAL,
            RiskLevel.HIGH,
            RequireConfirmation,
        ),
        (ToolPermissionMode.CONFIRM, ToolEffect.READ_PUBLIC, RiskLevel.LOW, RequireConfirmation),
    ],
)
async def test_modes_control_actual_tool_admission(mode, effect, risk, expected):
    gateway = DefaultToolPolicyGateway(registry(handler, risk=risk, effects=frozenset({effect})))
    result = await gateway.evaluate(request(), ToolPolicyContext(permission_mode=mode))
    assert isinstance(result, expected)


@pytest.mark.parametrize(
    "confirmation,risk",
    [
        (ConfirmationRequirement.FORBIDDEN, RiskLevel.LOW),
        (ConfirmationRequirement.POLICY, RiskLevel.CRITICAL),
    ],
)
async def test_full_mode_preserves_ineligible_tool_boundaries(confirmation, risk):
    gateway = DefaultToolPolicyGateway(registry(handler, confirmation=confirmation, risk=risk))
    assert isinstance(
        await gateway.evaluate(
            request(), ToolPolicyContext(permission_mode=ToolPermissionMode.FULL)
        ),
        Deny,
    )


async def test_critical_background_tool_is_denied():
    gateway = DefaultToolPolicyGateway(
        registry(handler, risk=RiskLevel.CRITICAL, latency=LatencyClass.BACKGROUND)
    )
    assert isinstance(
        await gateway.evaluate(
            request(), ToolPolicyContext(permission_mode=ToolPermissionMode.FULL)
        ),
        Deny,
    )


async def test_full_mode_does_not_bypass_scopes_or_single_use_grants():
    tools = registry(handler)
    gateway = DefaultToolPolicyGateway(tools)
    executor = ToolExecutor(tools, gateway)
    call = request()
    result = await gateway.evaluate(
        call, ToolPolicyContext(permission_mode=ToolPermissionMode.FULL)
    )
    assert isinstance(result, Allow)
    assert await executor.execute(call, result.grant) == "ok"
    with pytest.raises(GrantRejected):
        await executor.execute(call, result.grant)
    from server.tools.canonical import CanonicalTool
    from server.tools.registry import ToolRegistry

    class Source:
        def list_tools(self):
            return [
                CanonicalTool(
                    name="weather",
                    description="weather",
                    parameters={"type": "object"},
                    handler=handler,
                    required_scopes=frozenset({"private:read"}),
                )
            ]

    private = DefaultToolPolicyGateway(ToolRegistry([Source()]))
    assert isinstance(
        await private.evaluate(
            request(), ToolPolicyContext(permission_mode=ToolPermissionMode.FULL)
        ),
        Deny,
    )


async def test_updates_apply_to_new_calls_and_pending_calls_keep_their_decision(tmp_path):
    async def resolve(call):
        return await asyncio.to_thread(
            tool_permission_mode, call.context.user_id, "role-a", root=tmp_path
        )

    gateway = DefaultToolPolicyGateway(
        registry(handler, effects=frozenset({ToolEffect.READ_SENSITIVE}), risk=RiskLevel.MEDIUM),
        permission_resolver=resolve,
    )
    assert isinstance(await gateway.evaluate(request(call_id="first"), ToolPolicyContext()), Allow)
    write_settings(tmp_path, "confirm")
    pending = await gateway.evaluate(request(call_id="second"), ToolPolicyContext())
    assert isinstance(pending, RequireConfirmation)
    write_settings(tmp_path, "full")
    assert isinstance(await gateway.evaluate(request(call_id="third"), ToolPolicyContext()), Allow)
    again = await gateway.evaluate(request(call_id="second"), ToolPolicyContext())
    assert again == pending


def test_postgres_context_codec_preserves_mode_and_old_records():
    from server.persistence.postgres.tool_authorization import (
        _decode_policy_context,
        _encode_policy_context,
    )

    original = ToolPolicyContext(permission_mode=ToolPermissionMode.FULL)
    assert _decode_policy_context(_encode_policy_context(original)) == original
    assert (
        _decode_policy_context(
            {"authenticated_scopes": [], "policy_version": "old"}
        ).permission_mode
        is None
    )
