"""Server-authoritative tool policy, Bound Confirmation, and grant execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, TypeAlias

from server.core.interaction_context import InteractionContext
from server.tools.canonical import (
    ConfirmationRequirement,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolBinding,
    ToolEffect,
)
from server.tools.permission_settings import ToolPermissionMode
from server.tools.registry import ToolRegistry


class ToolOrigin(StrEnum):
    NATIVE_ENGINE = "native_engine"
    PIPELINE_BRAIN = "pipeline_brain"
    MCP = "mcp"
    AGENT = "agent"
    CLIENT = "client"
    APPLICATION = "application"


class ConfirmationChannel(StrEnum):
    VOICE = "voice"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class ToolRequest:
    call_id: str
    tool_name: str
    tool_version: str
    arguments: dict[str, Any]
    context: InteractionContext
    origin: ToolOrigin

    def __post_init__(self) -> None:
        if not self.call_id or not self.tool_name or not self.tool_version:
            raise ValueError("Tool Request identity must be non-empty")
        if self.context.call_id != self.call_id:
            raise ValueError("Tool Request context must carry the same call_id")
        _canonical_json(self.arguments)

    @property
    def arguments_json(self) -> str:
        return _canonical_json(self.arguments)

    @property
    def arguments_digest(self) -> str:
        return hashlib.sha256(self.arguments_json.encode()).hexdigest()

    @property
    def request_digest(self) -> str:
        value = ":".join(
            (
                self.context.tenant_id,
                self.context.user_id,
                self.context.voice_session_id,
                self.context.thread_id,
                self.call_id,
                self.tool_name,
                self.tool_version,
                self.arguments_digest,
                self.origin.value,
            )
        )
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolPolicyContext:
    authenticated_scopes: frozenset[str] = frozenset()
    policy_version: str = "default-v1"
    permission_mode: ToolPermissionMode | None = None


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    decision_id: str
    call_id: str
    policy_version: str
    context: InteractionContext
    tool_name: str
    tool_version: str
    arguments_digest: str
    allowed_scopes: frozenset[str]
    timeout_ms: int
    attempt_limit: int
    expires_at: datetime
    idempotency_key: str
    idempotency: IdempotencyClass
    confirmation_id: str | None = None


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    confirmation_id: str
    context: InteractionContext
    tool_name: str
    tool_version: str
    action_digest: str
    action_summary: str
    risk: RiskLevel
    requested_scopes: frozenset[str]
    required_channel: ConfirmationChannel
    expires_at: datetime
    policy_version: str


@dataclass(frozen=True, slots=True)
class Allow:
    grant: ExecutionGrant


@dataclass(frozen=True, slots=True)
class RequireConfirmation:
    pending: PendingConfirmation


@dataclass(frozen=True, slots=True)
class DelegateBackground:
    reason_code: str
    safe_message: str


@dataclass(frozen=True, slots=True)
class Deny:
    reason_code: str
    safe_message: str


ToolPolicyDecision: TypeAlias = Allow | RequireConfirmation | DelegateBackground | Deny


class GrantRejected(RuntimeError):
    pass


class ConfirmationRejected(RuntimeError):
    pass


class ToolAuthorizationConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PendingAuthorizationState:
    pending: PendingConfirmation
    request: ToolRequest
    policy_context: ToolPolicyContext


class ToolAuthorizationStore(Protocol):
    async def create_or_get_decision(
        self,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
        candidate: ToolPolicyDecision,
    ) -> ToolPolicyDecision: ...

    async def get_pending(
        self,
        confirmation_id: str,
    ) -> PendingAuthorizationState | None: ...

    async def resolve_confirmation(
        self,
        confirmation_id: str,
        resolution: ToolPolicyDecision,
    ) -> ToolPolicyDecision: ...

    async def consume_grant(
        self,
        grant: ExecutionGrant,
        *,
        request_digest: str,
    ) -> None: ...


class InMemoryToolAuthorizationStore:
    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str, str, str, str], tuple[str, ToolPolicyDecision]] = {}
        self._grants: dict[str, tuple[ExecutionGrant, str, bool]] = {}
        self._pending: dict[str, tuple[PendingAuthorizationState, bool]] = {}
        self._lock = asyncio.Lock()

    async def create_or_get_decision(
        self,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
        candidate: ToolPolicyDecision,
    ) -> ToolPolicyDecision:
        key = _request_key(request)
        async with self._lock:
            prior = self._decisions.get(key)
            if prior is not None:
                if prior[0] != request.request_digest:
                    raise ToolAuthorizationConflict(
                        "call_id was reused with a different Tool Request"
                    )
                return prior[1]
            self._decisions[key] = (request.request_digest, candidate)
            if isinstance(candidate, Allow):
                self._grants[candidate.grant.decision_id] = (
                    candidate.grant,
                    request.request_digest,
                    False,
                )
            elif isinstance(candidate, RequireConfirmation):
                state = PendingAuthorizationState(
                    pending=candidate.pending,
                    request=request,
                    policy_context=policy_context,
                )
                self._pending[candidate.pending.confirmation_id] = (state, False)
            return candidate

    async def get_pending(
        self,
        confirmation_id: str,
    ) -> PendingAuthorizationState | None:
        async with self._lock:
            stored = self._pending.get(confirmation_id)
            if stored is None or stored[1]:
                return None
            return stored[0]

    async def resolve_confirmation(
        self,
        confirmation_id: str,
        resolution: ToolPolicyDecision,
    ) -> ToolPolicyDecision:
        async with self._lock:
            stored = self._pending.get(confirmation_id)
            if stored is None or stored[1]:
                raise ConfirmationRejected("confirmation is missing or already consumed")
            state = stored[0]
            self._pending[confirmation_id] = (state, True)
            self._decisions[_request_key(state.request)] = (
                state.request.request_digest,
                resolution,
            )
            if isinstance(resolution, Allow):
                self._grants[resolution.grant.decision_id] = (
                    resolution.grant,
                    state.request.request_digest,
                    False,
                )
            return resolution

    async def consume_grant(
        self,
        grant: ExecutionGrant,
        *,
        request_digest: str,
    ) -> None:
        async with self._lock:
            stored = self._grants.get(grant.decision_id)
            if stored is None or stored[0] != grant:
                raise GrantRejected("grant is unknown or does not match authority state")
            stored_grant, stored_digest, consumed = stored
            if consumed:
                raise GrantRejected("grant was already consumed")
            if stored_grant.expires_at <= _utc_now():
                raise GrantRejected("grant expired")
            if stored_digest != request_digest:
                raise GrantRejected("grant does not match Tool Request")
            self._grants[grant.decision_id] = (stored_grant, stored_digest, True)


class DefaultToolPolicyGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        grant_ttl_seconds: float = 30,
        confirmation_ttl_seconds: float = 60,
        authorization_store: ToolAuthorizationStore | None = None,
        permission_resolver: Callable[[ToolRequest], Awaitable[ToolPermissionMode]] | None = None,
    ) -> None:
        if grant_ttl_seconds <= 0 or confirmation_ttl_seconds <= 0:
            raise ValueError("tool authorization TTLs must be positive")
        self._registry = registry
        self._grant_ttl = grant_ttl_seconds
        self._confirmation_ttl = confirmation_ttl_seconds
        self._authorization_store = authorization_store or InMemoryToolAuthorizationStore()
        self._permission_resolver = permission_resolver

    async def evaluate(
        self,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
    ) -> ToolPolicyDecision:
        if self._permission_resolver is not None:
            mode = await self._permission_resolver(request)
            policy_context = replace(
                policy_context,
                permission_mode=mode,
                policy_version=f"tool-permissions-v1:{mode.value}",
            )
        binding = self._registry.resolve_binding(
            request.tool_name,
            request.tool_version,
        )
        if binding is None:
            candidate: ToolPolicyDecision = Deny("unknown_tool", "请求的工具不可用。")
        else:
            validation_error = _validate_arguments(
                request.arguments,
                binding.descriptor.input_schema,
            )
            if validation_error is not None:
                candidate = Deny("invalid_arguments", "工具参数不符合约束。")
            elif not binding.descriptor.required_scopes.issubset(
                policy_context.authenticated_scopes
            ):
                candidate = Deny("missing_scope", "当前身份没有执行该操作的权限。")
            else:
                candidate = self._decide(request, binding, policy_context)
        try:
            return await self._authorization_store.create_or_get_decision(
                request,
                policy_context,
                candidate,
            )
        except ToolAuthorizationConflict:
            return Deny("call_id_conflict", "同一工具调用标识不能用于不同操作。")

    async def confirm(
        self,
        *,
        confirmation_id: str,
        action_digest: str,
        context: InteractionContext,
        channel: ConfirmationChannel,
        approved: bool,
    ) -> ToolPolicyDecision:
        state = await self._authorization_store.get_pending(confirmation_id)
        if state is None:
            raise ConfirmationRejected("confirmation is missing or already consumed")
        pending = state.pending
        if pending.expires_at <= _utc_now():
            raise ConfirmationRejected("confirmation expired")
        if action_digest != pending.action_digest or not _same_subject(context, pending.context):
            raise ConfirmationRejected("confirmation does not match the pending action")
        if (
            approved
            and pending.required_channel is ConfirmationChannel.STRONG
            and channel is not ConfirmationChannel.STRONG
        ):
            raise ConfirmationRejected("confirmation requires a stronger channel")
        if not approved:
            decision: ToolPolicyDecision = Deny(
                "confirmation_declined",
                "操作已取消。",
            )
        else:
            binding = self._require_binding(state.request)
            decision = Allow(
                self._issue_grant(
                    state.request,
                    binding,
                    state.policy_context,
                    confirmation_id=confirmation_id,
                )
            )
        return await self._authorization_store.resolve_confirmation(
            confirmation_id,
            decision,
        )

    async def pending_confirmation(
        self,
        confirmation_id: str,
    ) -> PendingAuthorizationState | None:
        """Return unresolved authority state without weakening confirmation checks."""

        return await self._authorization_store.get_pending(confirmation_id)

    async def consume(
        self,
        request: ToolRequest,
        grant: ExecutionGrant,
    ) -> ToolBinding:
        await self._authorization_store.consume_grant(
            grant,
            request_digest=request.request_digest,
        )
        return self._require_binding(request)

    def _decide(
        self,
        request: ToolRequest,
        binding: ToolBinding,
        policy_context: ToolPolicyContext,
    ) -> ToolPolicyDecision:
        descriptor = binding.descriptor
        if descriptor.confirmation is ConfirmationRequirement.FORBIDDEN:
            return Deny("forbidden_from_voice", "该工具不能从语音会话调用。")
        if descriptor.risk is RiskLevel.CRITICAL:
            return Deny("critical_risk", "该高风险操作不能在当前会话中执行。")
        if descriptor.latency is LatencyClass.BACKGROUND:
            return DelegateBackground("background_tool", "该操作已转入后台处理。")
        if policy_context.permission_mode is ToolPermissionMode.FULL:
            return Allow(self._issue_grant(request, binding, policy_context))
        required_channel: ConfirmationChannel | None = None
        if descriptor.confirmation is ConfirmationRequirement.STRONG:
            required_channel = ConfirmationChannel.STRONG
        elif (
            descriptor.confirmation is ConfirmationRequirement.ALWAYS
            or policy_context.permission_mode is ToolPermissionMode.CONFIRM
        ):
            required_channel = ConfirmationChannel.VOICE
        elif (
            policy_context.permission_mode is ToolPermissionMode.BALANCED
            and descriptor.effects
            <= {ToolEffect.NONE, ToolEffect.READ_PUBLIC, ToolEffect.READ_SENSITIVE}
            and descriptor.risk in {RiskLevel.LOW, RiskLevel.MEDIUM}
        ):
            required_channel = None
        elif descriptor.risk in {RiskLevel.MEDIUM, RiskLevel.HIGH} or descriptor.effects & {
            ToolEffect.READ_SENSITIVE,
            ToolEffect.WRITE_REVERSIBLE,
            ToolEffect.WRITE_IRREVERSIBLE,
            ToolEffect.EXECUTE_CODE,
            ToolEffect.COMMUNICATE_EXTERNAL,
            ToolEffect.SPEND_OR_TRANSFER,
            ToolEffect.CONTROL_DEVICE,
        }:
            required_channel = ConfirmationChannel.VOICE
        if required_channel is not None:
            pending = PendingConfirmation(
                confirmation_id=str(uuid.uuid4()),
                context=request.context,
                tool_name=request.tool_name,
                tool_version=request.tool_version,
                action_digest=request.arguments_digest,
                action_summary=f"执行 {descriptor.description}",
                risk=descriptor.risk,
                requested_scopes=descriptor.required_scopes,
                required_channel=required_channel,
                expires_at=_utc_now() + timedelta(seconds=self._confirmation_ttl),
                policy_version=policy_context.policy_version,
            )
            return RequireConfirmation(pending)
        return Allow(self._issue_grant(request, binding, policy_context))

    def _issue_grant(
        self,
        request: ToolRequest,
        binding: ToolBinding,
        policy_context: ToolPolicyContext,
        *,
        confirmation_id: str | None = None,
    ) -> ExecutionGrant:
        descriptor = binding.descriptor
        decision_id = str(uuid.uuid4())
        grant = ExecutionGrant(
            decision_id=decision_id,
            call_id=request.call_id,
            policy_version=policy_context.policy_version,
            context=request.context,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            arguments_digest=request.arguments_digest,
            allowed_scopes=descriptor.required_scopes,
            timeout_ms=descriptor.default_timeout_ms,
            attempt_limit=1,
            expires_at=_utc_now() + timedelta(seconds=self._grant_ttl),
            idempotency_key=str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"urn:voiceagent:tool:{request.request_digest}")
            ),
            idempotency=descriptor.idempotency,
            confirmation_id=confirmation_id,
        )
        return grant

    def _require_binding(self, request: ToolRequest) -> ToolBinding:
        binding = self._registry.resolve_binding(request.tool_name, request.tool_version)
        if binding is None:
            raise GrantRejected("tool binding disappeared")
        return binding


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        gateway: DefaultToolPolicyGateway,
    ) -> None:
        self._registry = registry
        self._gateway = gateway

    async def execute(self, request: ToolRequest, grant: ExecutionGrant) -> str:
        binding = await self._gateway.consume(request, grant)
        registered = self._registry.resolve_binding(request.tool_name, request.tool_version)
        if binding != registered:
            raise GrantRejected("authorized binding does not match executor registry")
        async with asyncio.timeout(grant.timeout_ms / 1000):
            result = await binding.executor(request.arguments)
        if not isinstance(result, str):
            raise ValueError("tool result must be a string")
        return result


def _request_key(request: ToolRequest) -> tuple[str, str, str, str, str]:
    return (
        request.context.tenant_id,
        request.context.user_id,
        request.context.voice_session_id,
        request.context.thread_id,
        request.call_id,
    )


def _same_subject(first: InteractionContext, second: InteractionContext) -> bool:
    return (
        first.tenant_id,
        first.user_id,
        first.device_id,
        first.voice_session_id,
        first.thread_id,
        first.call_id,
    ) == (
        second.tenant_id,
        second.user_id,
        second.device_id,
        second.voice_session_id,
        second.thread_id,
        second.call_id,
    )


def _validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
    if schema and schema.get("type", "object") != "object":
        return "root schema must be an object"
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return "invalid object schema"
    if any(name not in arguments for name in required):
        return "required property is missing"
    additional = schema.get("additionalProperties", False)
    if additional is not True and any(name not in properties for name in arguments):
        return "unknown property"
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if property_schema is not None and not _matches_schema_type(value, property_schema):
            return f"property {name!r} has the wrong type"
    return None


def _matches_schema_type(value: Any, schema: dict[str, Any]) -> bool:
    if "enum" in schema and value not in schema["enum"]:
        return False
    expected = schema.get("type")
    return {
        None: True,
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "null": value is None,
    }.get(expected, False)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("tool arguments must be JSON serializable") from error


def _utc_now() -> datetime:
    return datetime.now(UTC)
