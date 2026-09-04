"""BackendCatalog: a declarative name-to-launch-config mapping that named
`Driver`s are built from.

See CONTEXT.md — BackendCatalog, DelegationPolicy, and ADR-0031. Mirrors
qwen-audio-agent's own `shared/backend-catalog.mjs` — lets a `Router` hold
multiple named ACP-stdio `Driver`s without deployers hand-assembling launch
commands. `BackendLaunchConfig`'s fields mirror `AcpDriver.__init__`'s
`command`/`cwd`/`env`/`permission_policy` params exactly; `build_drivers` is
a thin translation from catalog entries to one `AcpDriver` (one subprocess)
per named backend.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from server.agent_session.driver_protocol import AgentDriver
from server.agent_session.plugins.acp_driver import AcpDriver
from server.agent_session.plugins.claude_stream_json import ClaudeStreamJsonDriver
from server.agent_session.plugins.codex_app_server import CodexAppServerDriver
from server.agent_session.plugins.hermes_acp import HermesAcpDriver
from server.agent_session.protocol import Driver


@dataclass(frozen=True)
class BackendLaunchConfig:
    command: Sequence[str]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    permission_policy: Callable[[dict[str, Any]], bool] = lambda _: False


BackendCatalog = Mapping[str, BackendLaunchConfig]


def build_drivers(catalog: BackendCatalog) -> dict[str, Driver]:
    return {
        name: AcpDriver(
            config.command,
            cwd=config.cwd,
            env=config.env,
            permission_policy=config.permission_policy,
        )
        for name, config in catalog.items()
    }


class AgentDriverKind(StrEnum):
    CODEX_APP_SERVER = "codex_app_server"
    CLAUDE_STREAM_JSON = "claude_stream_json"
    HERMES_ACP = "hermes_acp"


@dataclass(frozen=True)
class AgentBackendConfig:
    """Declarative construction config for universal v2 Agent Drivers."""

    kind: AgentDriverKind
    command: Sequence[str] | None = None
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    permission_policy: Callable[[dict[str, Any]], bool] = lambda _: False


AgentBackendCatalog = Mapping[str, AgentBackendConfig]


def build_agent_drivers(catalog: AgentBackendCatalog) -> dict[str, AgentDriver]:
    """Build named, interchangeable v2 drivers behind one protocol."""
    return {name: _build_agent_driver(config) for name, config in catalog.items()}


def _build_agent_driver(config: AgentBackendConfig) -> AgentDriver:
    if config.kind is AgentDriverKind.CODEX_APP_SERVER:
        if config.cwd is not None or config.env is not None:
            raise ValueError("Codex App Server cwd/env come from the supervised request")
        return CodexAppServerDriver(
            command=config.command or ("codex", "app-server", "--stdio")
        )
    if config.kind is AgentDriverKind.CLAUDE_STREAM_JSON:
        if config.cwd is not None:
            raise ValueError("Claude cwd comes from the supervised workspace lease")
        return ClaudeStreamJsonDriver(
            command=config.command or ("claude",),
            env=config.env,
        )
    if config.kind is AgentDriverKind.HERMES_ACP:
        acp = AcpDriver(
            command=config.command or ("hermes", "acp"),
            cwd=config.cwd,
            env=config.env,
            permission_policy=config.permission_policy,
        )
        return HermesAcpDriver(acp=acp)
    raise ValueError(f"unsupported Agent driver kind: {config.kind!r}")
