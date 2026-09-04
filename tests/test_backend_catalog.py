from server.agent_session.backend_catalog import (
    AgentBackendConfig,
    AgentDriverKind,
    BackendLaunchConfig,
    build_agent_drivers,
    build_drivers,
)
from server.agent_session.plugins.acp_driver import AcpDriver
from server.agent_session.plugins.claude_stream_json import ClaudeStreamJsonDriver
from server.agent_session.plugins.codex_app_server import CodexAppServerDriver
from server.agent_session.plugins.hermes_acp import HermesAcpDriver


def test_build_drivers_creates_one_acp_driver_per_catalog_entry():
    catalog = {
        "opencode": BackendLaunchConfig(command=("opencode", "acp")),
        "other-agent": BackendLaunchConfig(command=("other-agent", "acp")),
    }

    drivers = build_drivers(catalog)

    assert set(drivers) == {"opencode", "other-agent"}
    assert all(isinstance(driver, AcpDriver) for driver in drivers.values())


def test_build_drivers_passes_launch_config_fields_through():
    def permission_policy(_):
        return False

    config = BackendLaunchConfig(
        command=("opencode", "acp"),
        cwd="/tmp/workdir",
        env={"FOO": "bar"},
        permission_policy=permission_policy,
    )

    drivers = build_drivers({"opencode": config})

    driver = drivers["opencode"]
    assert driver._command == ("opencode", "acp")
    assert driver._cwd == "/tmp/workdir"
    assert driver._env == {"FOO": "bar"}
    assert driver._permission_policy is permission_policy


def test_build_agent_drivers_creates_modular_universal_driver_set():
    drivers = build_agent_drivers(
        {
            "codex": AgentBackendConfig(kind=AgentDriverKind.CODEX_APP_SERVER),
            "claude": AgentBackendConfig(kind=AgentDriverKind.CLAUDE_STREAM_JSON),
            "hermes": AgentBackendConfig(kind=AgentDriverKind.HERMES_ACP),
        }
    )

    assert isinstance(drivers["codex"], CodexAppServerDriver)
    assert isinstance(drivers["claude"], ClaudeStreamJsonDriver)
    assert isinstance(drivers["hermes"], HermesAcpDriver)


def test_new_catalog_uses_fail_closed_hermes_permission_policy():
    driver = build_agent_drivers(
        {"hermes": AgentBackendConfig(kind=AgentDriverKind.HERMES_ACP)}
    )["hermes"]

    assert isinstance(driver, HermesAcpDriver)
    assert driver._acp._permission_policy({}) is False
