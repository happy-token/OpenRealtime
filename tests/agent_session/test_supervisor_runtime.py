from __future__ import annotations

import asyncio

import pytest

from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.runtime import AgentSupervisorRuntime, SupervisorRuntimeConfig
from server.agent_session.supervisor import AgentTaskSupervisor
from server.agent_session.task_models import AgentTaskPhase
from server.persistence.in_memory import InMemoryPersistence
from tests.agent_session.test_durable_dispatch import make_request


async def _eventually(predicate, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_runtime_continuously_dispatches_without_manual_polling() -> None:
    persistence = InMemoryPersistence()
    driver = InMemoryAgentDriverV2(driver_kind="codex")
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": driver},
    )
    runtime = AgentSupervisorRuntime(
        supervisor,
        config=SupervisorRuntimeConfig(poll_interval_seconds=0.001),
    )

    await runtime.start()
    submission = await supervisor.submit(make_request())
    await _eventually(lambda: driver.start_count == 1)

    record = await supervisor.get(submission.record.worker_id)
    assert record is not None
    assert record.phase is AgentTaskPhase.RUNNING
    assert runtime.snapshot.running is True
    assert runtime.snapshot.dispatch_cycles > 0
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_recovers_before_first_dispatch_and_survives_transient_error() -> None:
    calls: list[str] = []
    dispatched = asyncio.Event()

    class FakeSupervisor:
        async def recover_active(self):
            calls.append("recover")
            return ("worker-1",)

        async def dispatch_once(self, **kwargs):
            del kwargs
            calls.append("dispatch")
            if calls.count("dispatch") == 1:
                raise ConnectionError("database temporarily unavailable")
            dispatched.set()
            return ()

        async def shutdown(self):
            calls.append("shutdown")

    runtime = AgentSupervisorRuntime(
        FakeSupervisor(),
        config=SupervisorRuntimeConfig(
            poll_interval_seconds=0.001,
            error_backoff_seconds=0.001,
        ),
    )

    recovered = await runtime.start()
    await asyncio.wait_for(dispatched.wait(), timeout=1)

    assert recovered == ("worker-1",)
    assert calls[0] == "recover"
    assert runtime.snapshot.consecutive_errors == 0
    assert runtime.snapshot.last_error is not None
    await runtime.close()
    assert calls[-1] == "shutdown"


@pytest.mark.asyncio
async def test_runtime_start_and_close_are_idempotent() -> None:
    class FakeSupervisor:
        shutdown_count = 0

        async def recover_active(self):
            return ()

        async def dispatch_once(self, **kwargs):
            del kwargs
            return ()

        async def shutdown(self):
            self.shutdown_count += 1

    supervisor = FakeSupervisor()
    runtime = AgentSupervisorRuntime(
        supervisor,
        config=SupervisorRuntimeConfig(poll_interval_seconds=0.001),
    )

    await runtime.start()
    assert await runtime.start() == ()
    await runtime.close()
    await runtime.close()

    assert supervisor.shutdown_count == 1
    assert runtime.snapshot.running is False
