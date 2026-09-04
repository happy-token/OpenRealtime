from __future__ import annotations

from server.cli.lifecycle import invoke_lifecycle_hook
from server.endpoint_session.registry import EndpointSessionRegistry


async def test_console_mode_runs_the_same_application_lifecycle(monkeypatch) -> None:
    from server.cli import harness

    calls: list[str] = []

    async def startup() -> str:
        calls.append("startup")
        return "state"

    async def shutdown(state: object) -> None:
        calls.append(f"shutdown:{state}")

    async def dispatch(*args, **kwargs) -> None:
        del args, kwargs
        calls.append("dispatch")

    monkeypatch.setattr(harness, "_dispatch", dispatch)

    await harness._run(
        "console",
        lambda transport: transport,
        serve=lambda *args, **kwargs: None,
        session_registry=None,
        host="127.0.0.1",
        port=8765,
        control_plane_port=None,
        on_startup=startup,
        on_shutdown=shutdown,
    )

    assert calls == ["startup", "dispatch", "shutdown:state"]


async def test_lifecycle_helper_awaits_async_startup_and_shutdown_hooks() -> None:
    lifecycle: list[str] = []

    async def startup() -> str:
        lifecycle.append("startup")
        return "state"

    async def shutdown(state: object) -> None:
        lifecycle.append(f"shutdown:{state}")

    state = await invoke_lifecycle_hook(startup)
    lifecycle.append("serve")
    await invoke_lifecycle_hook(shutdown, state)

    assert lifecycle == ["startup", "serve", "shutdown:state"]


async def test_runtime_closes_control_plane_after_realtime_server_stops(
    monkeypatch,
) -> None:
    from server.cli import harness

    calls: list[str] = []

    class FakeControlPlane:
        def stop_accepting_avatar_requests(self) -> None:
            calls.append("control-plane.stop-avatar")

        def shutdown(self) -> None:
            calls.append("control-plane.shutdown")

        async def drain_avatar_requests(self, *, deadline_s: float) -> int:
            calls.append(f"avatar.drain:{deadline_s:g}")
            return 0

        def server_close(self) -> None:
            calls.append("control-plane.close")

    def start(*args, **kwargs):
        del args, kwargs
        calls.append("control-plane.start")
        return FakeControlPlane()

    async def serve(*args, **kwargs):
        del args, kwargs
        calls.append("realtime.serve")

    async def shutdown(state: object) -> None:
        assert state is None
        calls.append("application.shutdown")

    class RecordingRegistry(EndpointSessionRegistry):
        async def drain(self, *, deadline_s: float = 15.0) -> tuple[str, ...]:
            calls.append(f"voice.drain:{deadline_s:g}")
            return ()

    monkeypatch.setattr(harness.control_plane_http, "start", start)

    await harness._run(
        "dev",
        lambda transport: transport,
        serve=serve,
        session_registry=RecordingRegistry(),
        host="127.0.0.1",
        port=8765,
        control_plane_port=8766,
        on_startup=None,
        on_shutdown=shutdown,
    )

    assert calls == [
        "control-plane.start",
        "realtime.serve",
        "control-plane.stop-avatar",
        "voice.drain:15",
        "control-plane.shutdown",
        "avatar.drain:15",
        "control-plane.close",
        "application.shutdown",
    ]
