"""Canonical Tool Schema: the single tool shape a Brain consumes.

MCP servers, function-calling declarations, and skills are all adapted into
this one shape by the source modules in this package before a Brain ever
sees them — see CONTEXT.md — Canonical Tool Schema, and ADR-0001.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


class ToolEffect(StrEnum):
    NONE = "none"
    READ_PUBLIC = "read_public"
    READ_SENSITIVE = "read_sensitive"
    WRITE_REVERSIBLE = "write_reversible"
    WRITE_IRREVERSIBLE = "write_irreversible"
    EXECUTE_CODE = "execute_code"
    COMMUNICATE_EXTERNAL = "communicate_external"
    SPEND_OR_TRANSFER = "spend_or_transfer"
    CONTROL_DEVICE = "control_device"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IdempotencyClass(StrEnum):
    IDEMPOTENT = "idempotent"
    KEYED = "keyed"
    NON_IDEMPOTENT = "non_idempotent"
    UNKNOWN = "unknown"


class LatencyClass(StrEnum):
    FAST = "fast"
    VARIABLE = "variable"
    BACKGROUND = "background"


class ConfirmationRequirement(StrEnum):
    POLICY = "policy"
    ALWAYS = "always"
    STRONG = "strong"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    effects: frozenset[ToolEffect]
    risk: RiskLevel
    idempotency: IdempotencyClass
    latency: LatencyClass
    confirmation: ConfirmationRequirement
    required_scopes: frozenset[str]
    default_timeout_ms: int

    def __post_init__(self) -> None:
        if not self.name or not self.version or not self.description:
            raise ValueError("tool descriptor identity and description must be non-empty")
        if not self.effects:
            raise ValueError("tool descriptor effects must be declared")
        if self.default_timeout_ms < 1:
            raise ValueError("tool default_timeout_ms must be positive")


@dataclass(frozen=True, slots=True)
class ToolBinding:
    descriptor: ToolDescriptor
    executor: ToolHandler
    credential_profile: str | None = None
    sandbox_profile: str | None = None


@dataclass(frozen=True)
class CanonicalTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    version: str = "1.0.0"
    output_schema: dict[str, Any] | None = None
    effects: frozenset[ToolEffect] = frozenset({ToolEffect.WRITE_IRREVERSIBLE})
    risk: RiskLevel = RiskLevel.HIGH
    idempotency: IdempotencyClass = IdempotencyClass.UNKNOWN
    latency: LatencyClass = LatencyClass.VARIABLE
    confirmation: ConfirmationRequirement = ConfirmationRequirement.POLICY
    required_scopes: frozenset[str] = frozenset()
    default_timeout_ms: int = 3000

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name=self.name,
            version=self.version,
            description=self.description,
            input_schema=self.parameters,
            output_schema=self.output_schema,
            effects=self.effects,
            risk=self.risk,
            idempotency=self.idempotency,
            latency=self.latency,
            confirmation=self.confirmation,
            required_scopes=self.required_scopes,
            default_timeout_ms=self.default_timeout_ms,
        )

    def to_binding(self) -> ToolBinding:
        return ToolBinding(descriptor=self.descriptor, executor=self.handler)
