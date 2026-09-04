"""PostgreSQL authority state for tool decisions, confirmations, and grants."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from server.core.interaction_context import InteractionContext
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name
from server.tools.canonical import IdempotencyClass, RiskLevel
from server.tools.policy_gateway import (
    Allow,
    ConfirmationChannel,
    ConfirmationRejected,
    DelegateBackground,
    Deny,
    ExecutionGrant,
    GrantRejected,
    PendingAuthorizationState,
    PendingConfirmation,
    RequireConfirmation,
    ToolAuthorizationConflict,
    ToolOrigin,
    ToolPolicyContext,
    ToolPolicyDecision,
    ToolRequest,
)


class PostgresToolAuthorizationStore:
    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._decisions = f'"{validated}".tool_policy_decisions'
        self._pending = f'"{validated}".tool_pending_confirmations'
        self._grants = f'"{validated}".tool_execution_grants'

    async def create_or_get_decision(
        self,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
        candidate: ToolPolicyDecision,
    ) -> ToolPolicyDecision:
        now = _utc_now()
        key = _request_key_values(request)
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    f"""
                    INSERT INTO {self._decisions} (
                        tenant_id, user_id, voice_session_id, thread_id, call_id,
                        request_digest, request_payload, policy_context_payload,
                        decision_payload, created_at, updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7::jsonb, $8::jsonb,
                        $9::jsonb, $10, $10
                    )
                    ON CONFLICT (
                        tenant_id, user_id, voice_session_id, thread_id, call_id
                    ) DO NOTHING
                    RETURNING *
                    """,
                    *key,
                    request.request_digest,
                    _json(_encode_request(request)),
                    _json(_encode_policy_context(policy_context)),
                    _json(_encode_decision(candidate)),
                    now,
                )
                if row is None:
                    row = await connection.fetchrow(
                        f"""
                        SELECT * FROM {self._decisions}
                        WHERE tenant_id = $1 AND user_id = $2
                          AND voice_session_id = $3 AND thread_id = $4 AND call_id = $5
                        """,
                        *key,
                    )
                    if row is None:
                        raise RuntimeError("tool policy decision disappeared")
                    if row["request_digest"] != request.request_digest:
                        raise ToolAuthorizationConflict(
                            "call_id was reused with a different Tool Request"
                        )
                    return _decode_decision(_object(row["decision_payload"]))
                await self._insert_authority_state(
                    connection,
                    request=request,
                    policy_context=policy_context,
                    decision=candidate,
                    now=now,
                )
                return candidate

    async def get_pending(
        self,
        confirmation_id: str,
    ) -> PendingAuthorizationState | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._pending}
                WHERE confirmation_id = $1 AND consumed_at IS NULL
                """,
                confirmation_id,
            )
            if row is None:
                return None
            return PendingAuthorizationState(
                pending=_decode_pending(_object(row["pending_payload"])),
                request=_decode_request(_object(row["request_payload"])),
                policy_context=_decode_policy_context(
                    _object(row["policy_context_payload"])
                ),
            )

    async def resolve_confirmation(
        self,
        confirmation_id: str,
        resolution: ToolPolicyDecision,
    ) -> ToolPolicyDecision:
        now = _utc_now()
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._pending}
                    WHERE confirmation_id = $1
                    FOR UPDATE
                    """,
                    confirmation_id,
                )
                if row is None or row["consumed_at"] is not None:
                    raise ConfirmationRejected(
                        "confirmation is missing or already consumed"
                    )
                request = _decode_request(_object(row["request_payload"]))
                await connection.execute(
                    f"""
                    UPDATE {self._pending}
                    SET consumed_at = $2, resolution_payload = $3::jsonb
                    WHERE confirmation_id = $1
                    """,
                    confirmation_id,
                    now,
                    _json(_encode_decision(resolution)),
                )
                await connection.execute(
                    f"""
                    UPDATE {self._decisions}
                    SET decision_payload = $6::jsonb, updated_at = $7
                    WHERE tenant_id = $1 AND user_id = $2
                      AND voice_session_id = $3 AND thread_id = $4 AND call_id = $5
                    """,
                    *_request_key_values(request),
                    _json(_encode_decision(resolution)),
                    now,
                )
                if isinstance(resolution, Allow):
                    await self._insert_grant(
                        connection,
                        request=request,
                        grant=resolution.grant,
                        now=now,
                    )
                return resolution

    async def consume_grant(
        self,
        grant: ExecutionGrant,
        *,
        request_digest: str,
    ) -> None:
        now = _utc_now()
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._grants}
                    WHERE decision_id = $1
                    FOR UPDATE
                    """,
                    grant.decision_id,
                )
                if row is None or _decode_grant(_object(row["grant_payload"])) != grant:
                    raise GrantRejected(
                        "grant is unknown or does not match authority state"
                    )
                if row["consumed_at"] is not None:
                    raise GrantRejected("grant was already consumed")
                if row["expires_at"] <= now:
                    raise GrantRejected("grant expired")
                if row["request_digest"] != request_digest:
                    raise GrantRejected("grant does not match Tool Request")
                await connection.execute(
                    f"""
                    UPDATE {self._grants}
                    SET consumed_at = $2
                    WHERE decision_id = $1
                    """,
                    grant.decision_id,
                    now,
                )

    async def _insert_authority_state(
        self,
        connection: Any,
        *,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
        decision: ToolPolicyDecision,
        now: datetime,
    ) -> None:
        if isinstance(decision, Allow):
            await self._insert_grant(
                connection,
                request=request,
                grant=decision.grant,
                now=now,
            )
        elif isinstance(decision, RequireConfirmation):
            pending = decision.pending
            await connection.execute(
                f"""
                INSERT INTO {self._pending} (
                    confirmation_id, tenant_id, user_id, voice_session_id,
                    thread_id, call_id, pending_payload, request_payload,
                    policy_context_payload, expires_at, created_at
                )
                VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7::jsonb, $8::jsonb,
                    $9::jsonb, $10, $11
                )
                """,
                pending.confirmation_id,
                *_request_key_values(request),
                _json(_encode_pending(pending)),
                _json(_encode_request(request)),
                _json(_encode_policy_context(policy_context)),
                pending.expires_at,
                now,
            )

    async def _insert_grant(
        self,
        connection: Any,
        *,
        request: ToolRequest,
        grant: ExecutionGrant,
        now: datetime,
    ) -> None:
        await connection.execute(
            f"""
            INSERT INTO {self._grants} (
                decision_id, tenant_id, user_id, voice_session_id,
                thread_id, call_id, request_digest, grant_payload,
                expires_at, created_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8::jsonb,
                $9, $10
            )
            """,
            grant.decision_id,
            *_request_key_values(request),
            request.request_digest,
            _json(_encode_grant(grant)),
            grant.expires_at,
            now,
        )


def _encode_context(context: InteractionContext) -> dict[str, Any]:
    return {
        field: getattr(context, field)
        for field in (
            "tenant_id",
            "user_id",
            "device_id",
            "voice_session_id",
            "thread_id",
            "turn_id",
            "generation",
            "response_id",
            "call_id",
            "worker_id",
            "confirmation_id",
            "handoff_id",
        )
    }


def _decode_context(payload: dict[str, Any]) -> InteractionContext:
    return InteractionContext(**payload)


def _encode_request(request: ToolRequest) -> dict[str, Any]:
    return {
        "call_id": request.call_id,
        "tool_name": request.tool_name,
        "tool_version": request.tool_version,
        "arguments": request.arguments,
        "context": _encode_context(request.context),
        "origin": request.origin.value,
    }


def _decode_request(payload: dict[str, Any]) -> ToolRequest:
    return ToolRequest(
        call_id=payload["call_id"],
        tool_name=payload["tool_name"],
        tool_version=payload["tool_version"],
        arguments=payload["arguments"],
        context=_decode_context(payload["context"]),
        origin=ToolOrigin(payload["origin"]),
    )


def _encode_policy_context(context: ToolPolicyContext) -> dict[str, Any]:
    return {
        "authenticated_scopes": sorted(context.authenticated_scopes),
        "policy_version": context.policy_version,
    }


def _decode_policy_context(payload: dict[str, Any]) -> ToolPolicyContext:
    return ToolPolicyContext(
        authenticated_scopes=frozenset(payload["authenticated_scopes"]),
        policy_version=payload["policy_version"],
    )


def _encode_grant(grant: ExecutionGrant) -> dict[str, Any]:
    return {
        "decision_id": grant.decision_id,
        "call_id": grant.call_id,
        "policy_version": grant.policy_version,
        "context": _encode_context(grant.context),
        "tool_name": grant.tool_name,
        "tool_version": grant.tool_version,
        "arguments_digest": grant.arguments_digest,
        "allowed_scopes": sorted(grant.allowed_scopes),
        "timeout_ms": grant.timeout_ms,
        "attempt_limit": grant.attempt_limit,
        "expires_at": grant.expires_at.isoformat(),
        "idempotency_key": grant.idempotency_key,
        "idempotency": grant.idempotency.value,
        "confirmation_id": grant.confirmation_id,
    }


def _decode_grant(payload: dict[str, Any]) -> ExecutionGrant:
    return ExecutionGrant(
        decision_id=payload["decision_id"],
        call_id=payload["call_id"],
        policy_version=payload["policy_version"],
        context=_decode_context(payload["context"]),
        tool_name=payload["tool_name"],
        tool_version=payload["tool_version"],
        arguments_digest=payload["arguments_digest"],
        allowed_scopes=frozenset(payload["allowed_scopes"]),
        timeout_ms=payload["timeout_ms"],
        attempt_limit=payload["attempt_limit"],
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        idempotency_key=payload["idempotency_key"],
        idempotency=IdempotencyClass(payload["idempotency"]),
        confirmation_id=payload["confirmation_id"],
    )


def _encode_pending(pending: PendingConfirmation) -> dict[str, Any]:
    return {
        "confirmation_id": pending.confirmation_id,
        "context": _encode_context(pending.context),
        "tool_name": pending.tool_name,
        "tool_version": pending.tool_version,
        "action_digest": pending.action_digest,
        "action_summary": pending.action_summary,
        "risk": pending.risk.value,
        "requested_scopes": sorted(pending.requested_scopes),
        "required_channel": pending.required_channel.value,
        "expires_at": pending.expires_at.isoformat(),
        "policy_version": pending.policy_version,
    }


def _decode_pending(payload: dict[str, Any]) -> PendingConfirmation:
    return PendingConfirmation(
        confirmation_id=payload["confirmation_id"],
        context=_decode_context(payload["context"]),
        tool_name=payload["tool_name"],
        tool_version=payload["tool_version"],
        action_digest=payload["action_digest"],
        action_summary=payload["action_summary"],
        risk=RiskLevel(payload["risk"]),
        requested_scopes=frozenset(payload["requested_scopes"]),
        required_channel=ConfirmationChannel(payload["required_channel"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        policy_version=payload["policy_version"],
    )


def _encode_decision(decision: ToolPolicyDecision) -> dict[str, Any]:
    if isinstance(decision, Allow):
        return {"type": "allow", "grant": _encode_grant(decision.grant)}
    if isinstance(decision, RequireConfirmation):
        return {
            "type": "require_confirmation",
            "pending": _encode_pending(decision.pending),
        }
    if isinstance(decision, DelegateBackground):
        return {
            "type": "delegate_background",
            "reason_code": decision.reason_code,
            "safe_message": decision.safe_message,
        }
    return {
        "type": "deny",
        "reason_code": decision.reason_code,
        "safe_message": decision.safe_message,
    }


def _decode_decision(payload: dict[str, Any]) -> ToolPolicyDecision:
    decision_type = payload["type"]
    if decision_type == "allow":
        return Allow(_decode_grant(payload["grant"]))
    if decision_type == "require_confirmation":
        return RequireConfirmation(_decode_pending(payload["pending"]))
    if decision_type == "delegate_background":
        return DelegateBackground(payload["reason_code"], payload["safe_message"])
    if decision_type == "deny":
        return Deny(payload["reason_code"], payload["safe_message"])
    raise ValueError(f"unsupported tool policy decision: {decision_type!r}")


def _request_key_values(request: ToolRequest) -> tuple[str, str, str, str, str]:
    context = request.context
    return (
        context.tenant_id,
        context.user_id,
        context.voice_session_id,
        context.thread_id,
        request.call_id,
    )


def _object(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("tool authorization payload must decode to an object")
    return decoded


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
