"""Execution deadlines remain bounded even for uncooperative classifier plugins."""
from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from server.observability.telemetry import SessionTelemetry, TelemetryIdentity, TelemetryOutcome
from server.turn_policy.classifier_execution import (
    CLASSIFIER_STAGE_OBSERVER,
    ClassificationCapacityError,
    ClassificationExecutor,
    classification_stage,
    run_classification,
)


def recording_telemetry():
    records = []
    runtime = Mock(_enqueue=records.append)
    identity = TelemetryIdentity("tenant", "user", "device", "session", "thread")
    return SessionTelemetry(runtime, identity), records


async def test_deadline_does_not_wait_for_a_classifier_that_suppresses_cancellation() -> None:
    cancelled = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)

    async def stubborn() -> str:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return "late success"

    call = asyncio.create_task(run_classification(
        stubborn, operation="eot", timeout_s=0.01,
        telemetry=None, generation=1, attributes={}, executor=executor,
    ))
    try:
        await asyncio.wait_for(cancelled.wait(), 0.5)
        await asyncio.sleep(0)
        assert call.done(), "the classifier deadline must not wait for cancellation cooperation"
        with pytest.raises(TimeoutError):
            await call
        assert executor.pending_count == 1
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        await asyncio.sleep(0)
        assert await executor.close() == 0


async def test_caller_cancellation_is_bounded_and_requests_provider_cancellation() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)

    async def stubborn() -> str:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return "late success"

    call = asyncio.create_task(executor.run(stubborn, timeout_s=10))
    try:
        await started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert executor.pending_count == 1
    finally:
        release.set()
        assert await executor.close() == 0


async def test_stuck_cancelled_provider_occupies_capacity_without_new_provider_calls() -> None:
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    invoked = 0

    async def stubborn() -> str:
        nonlocal invoked
        invoked += 1
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()
            return "late success"

    try:
        with pytest.raises(TimeoutError):
            await run_classification(stubborn, operation="eot", timeout_s=0.01,
                telemetry=telemetry, generation=1, attributes={}, executor=executor)
        for _ in range(20):
            with pytest.raises(ClassificationCapacityError):
                await run_classification(stubborn, operation="eot", timeout_s=0.01,
                    telemetry=telemetry, generation=2, attributes={}, executor=executor)
        assert invoked == 1
        assert executor.pending_count == 1
        provider_records = [record for record in records if record.name.startswith("provider.")]
        assert len(provider_records) == 1
        assert provider_records[0].outcome is TelemetryOutcome.TIMEOUT
        rejections = [record for record in records if record.name == "turn_policy.classification_rejected"]
        assert len(rejections) == 20
        assert all(record.attributes["reason"] == "capacity" for record in rejections)
    finally:
        release.set()
        assert await executor.close() == 0


async def test_close_is_bounded_and_keeps_unfinished_provider_tracked() -> None:
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)

    async def stubborn() -> str:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return "late success"

    try:
        with pytest.raises(TimeoutError):
            await executor.run(stubborn, timeout_s=0.01)
        assert await executor.close(timeout_s=0.01) == 1
        assert executor.pending_count == 1
        with pytest.raises(RuntimeError, match="closed"):
            await executor.run(stubborn, timeout_s=1)
    finally:
        release.set()
        assert await executor.close() == 0


async def test_timeout_records_terminal_timeout_and_suppresses_late_success_stage() -> None:
    release = asyncio.Event()
    cancelled = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    parent_observer = Mock()

    async def stubborn() -> str:
        with classification_stage("jev", "request"):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return "late success"

    token = CLASSIFIER_STAGE_OBSERVER.set(parent_observer)
    try:
        with pytest.raises(TimeoutError):
            await run_classification(stubborn, operation="eot", timeout_s=0.01,
                telemetry=telemetry, generation=3, attributes={"chunk_id": "chunk-3"},
                executor=executor)
        assert CLASSIFIER_STAGE_OBSERVER.get() is parent_observer
        await cancelled.wait()
        assert len(records) == 1
        assert records[0].name == "provider.eot_classifier.classify"
        assert records[0].outcome is TelemetryOutcome.TIMEOUT
        assert records[0].attributes["ttfb_ms"] is None
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(records) == 1
        parent_observer.assert_not_called()
        assert executor.pending_count == 0
    finally:
        CLASSIFIER_STAGE_OBSERVER.reset(token)
        release.set()
        assert await executor.close() == 0


async def test_concurrent_classifications_keep_stage_context_and_metadata_separate() -> None:
    executor = ClassificationExecutor(max_pending=2)
    telemetry, records = recording_telemetry()
    parent_observer = Mock()

    async def classify(value: str) -> str:
        with classification_stage("jev", "request"):
            await asyncio.sleep(0)
            return value

    token = CLASSIFIER_STAGE_OBSERVER.set(parent_observer)
    try:
        result = await asyncio.gather(*(
            run_classification(lambda value=operation: classify(value),
                operation=operation, timeout_s=1, telemetry=telemetry,
                generation=generation, attributes={"chunk_id": operation}, executor=executor)
            for operation, generation in (("eot", 1), ("interruption", 2))
        ))
        assert result == ["eot", "interruption"]
        assert CLASSIFIER_STAGE_OBSERVER.get() is parent_observer
        stages = [record for record in records if record.name.startswith("jev.")]
        assert {(record.name, record.generation, record.attributes["chunk_id"]) for record in stages} == {
            ("jev.eot.request", 1, "eot"), ("jev.interruption.request", 2, "interruption"),
        }
        assert all(record.outcome is TelemetryOutcome.OK for record in records)
        assert all(record.attributes["ttfb_ms"] is not None
            for record in records if record.name.startswith("provider."))
        parent_observer.assert_not_called()
    finally:
        CLASSIFIER_STAGE_OBSERVER.reset(token)
        assert await executor.close() == 0


async def test_provider_error_propagates_with_error_stage_and_terminal() -> None:
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    error = ValueError("classifier failed")

    async def fail() -> str:
        with classification_stage("jev", "request"):
            raise error

    with pytest.raises(ValueError) as caught:
        await run_classification(fail, operation="eot", timeout_s=1,
            telemetry=telemetry, generation=1, attributes={}, executor=executor)
    assert caught.value is error
    assert {record.name for record in records} == {"jev.eot.request", "provider.eot_classifier.classify"}
    assert all(record.outcome is TelemetryOutcome.ERROR for record in records)
    assert await executor.close() == 0


async def test_caller_cancellation_records_cancelled_not_provider_success() -> None:
    started = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()

    async def wait() -> str:
        started.set()
        await asyncio.Future()
        return "unreachable"

    call = asyncio.create_task(run_classification(wait, operation="interruption", timeout_s=10,
        telemetry=telemetry, generation=1, attributes={}, executor=executor))
    await started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert len(records) == 1
    assert records[0].outcome is TelemetryOutcome.CANCELLED
    assert records[0].attributes["ttfb_ms"] is None
    assert await executor.close() == 0


async def test_abandoned_provider_failure_is_retrieved_and_capacity_recovers(caplog) -> None:
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)

    async def fail_late() -> str:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()
            raise ValueError("late failure")

    with pytest.raises(TimeoutError):
        await executor.run(fail_late, timeout_s=0.01)
    await asyncio.sleep(0)
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert executor.pending_count == 0
    assert "Discarded classifier failed after cancellation: ValueError" in caplog.text
    assert "exception was never retrieved" not in caplog.text
    assert await executor.close() == 0


async def test_no_telemetry_preserves_parent_stage_observer_for_valid_result() -> None:
    executor = ClassificationExecutor(max_pending=1)
    observer = Mock()

    async def classify() -> str:
        with classification_stage("other", "request"):
            return "complete"

    token = CLASSIFIER_STAGE_OBSERVER.set(observer)
    try:
        assert await run_classification(classify, operation="eot", timeout_s=1,
            telemetry=None, generation=1, attributes={}, executor=executor) == "complete"
        assert observer.call_args.args[0] == "other.request"
        assert observer.call_args.args[2] == "ok"
        assert CLASSIFIER_STAGE_OBSERVER.get() is observer
    finally:
        CLASSIFIER_STAGE_OBSERVER.reset(token)
        assert await executor.close() == 0


async def test_cancel_then_replace_cooperative_provider_reuses_single_execution_slot() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    replacement = Mock()

    async def old_provider() -> str:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async def new_provider() -> str:
        replacement()
        return "latest complete"

    old_call = asyncio.create_task(run_classification(old_provider,
        operation="eot", timeout_s=1, telemetry=telemetry,
        generation=1, attributes={"chunk_id": "old"}, executor=executor))
    try:
        await started.wait()
        old_call.cancel()
        new_call = asyncio.create_task(run_classification(new_provider,
            operation="eot", timeout_s=1, telemetry=telemetry,
            generation=1, attributes={"chunk_id": "new"}, executor=executor))
        assert await new_call == "latest complete"
        replacement.assert_called_once()
        assert cancelled.is_set()
        waits = [record for record in records if record.name == "turn_policy.eot_capacity_wait"]
        assert len(waits) == 1
        assert waits[0].outcome is TelemetryOutcome.OK
        assert not any(record.name == "turn_policy.classification_rejected" for record in records)
    finally:
        old_call.cancel()
        await asyncio.gather(old_call, return_exceptions=True)
        assert await executor.close() == 0


@pytest.mark.parametrize("max_pending", [True, False, 1.5, "2", None])
def test_execution_capacity_requires_a_positive_integer(max_pending) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ClassificationExecutor(max_pending=max_pending)


async def test_cancel_handoff_wait_for_uncooperative_provider_has_fixed_bound() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    replacement = Mock()

    async def old_provider() -> str:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()
            return "late success"

    async def new_provider() -> str:
        replacement()
        return "new result"

    old_call = asyncio.create_task(executor.run(old_provider, timeout_s=10))
    try:
        await started.wait()
        old_call.cancel()
        with pytest.raises(ClassificationCapacityError):
            await asyncio.wait_for(run_classification(new_provider, operation="eot",
                timeout_s=1, telemetry=telemetry, generation=2, attributes={}, executor=executor),
                timeout=0.2)
        replacement.assert_not_called()
        assert executor.pending_count == 1
        waits = [record for record in records if record.name == "turn_policy.eot_capacity_wait"]
        assert len(waits) == 1
        assert waits[0].outcome is TelemetryOutcome.TIMEOUT
        assert not any(record.name.startswith("provider.") for record in records)
    finally:
        old_call.cancel()
        await asyncio.gather(old_call, return_exceptions=True)
        release.set()
        assert await executor.close() == 0


@pytest.mark.parametrize("with_telemetry", [False, True])
async def test_cancellation_cleanup_and_provider_share_one_absolute_deadline(with_telemetry) -> None:
    started = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    replacement = Mock()
    telemetry, records = recording_telemetry()

    async def old_provider() -> str:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            raise

    async def new_provider() -> str:
        replacement()
        await asyncio.sleep(0.045)
        return "new result"

    old_call = asyncio.create_task(executor.run(old_provider, timeout_s=10))
    try:
        await started.wait()
        old_call.cancel()
        with pytest.raises(TimeoutError):
            if with_telemetry:
                await run_classification(new_provider, operation="eot", timeout_s=0.055,
                    telemetry=telemetry, generation=2, attributes={}, executor=executor)
            else:
                await executor.run(new_provider, timeout_s=0.055)
        replacement.assert_called_once()
        if with_telemetry:
            assert [record.outcome for record in records] == [
                TelemetryOutcome.OK, TelemetryOutcome.TIMEOUT,
            ]
            assert records[0].name == "turn_policy.eot_capacity_wait"
            assert records[1].name == "provider.eot_classifier.classify"
            assert records[1].timeout_ms == 55
            assert 0 < records[1].attributes["effective_timeout_ms"] < (
                records[1].timeout_ms - records[0].duration_ms / 2
            )
    finally:
        old_call.cancel()
        await asyncio.gather(old_call, return_exceptions=True)
        assert await executor.close() == 0


async def test_capacity_wait_cancellation_does_not_start_replacement_provider() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()
    replacement = Mock()

    async def old_provider() -> str:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()
            return "late success"

    async def new_provider() -> str:
        replacement()
        return "new result"

    old_call = asyncio.create_task(executor.run(old_provider, timeout_s=10))
    try:
        await started.wait()
        old_call.cancel()
        new_call = asyncio.create_task(run_classification(new_provider, operation="eot",
            timeout_s=1, telemetry=telemetry, generation=2, attributes={}, executor=executor))
        await asyncio.sleep(0)
        new_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await new_call
        replacement.assert_not_called()
        assert [record.outcome for record in records] == [TelemetryOutcome.CANCELLED]
        assert records[0].name == "turn_policy.eot_capacity_wait"
    finally:
        old_call.cancel()
        await asyncio.gather(old_call, return_exceptions=True)
        release.set()
        assert await executor.close() == 0


async def test_close_invalidates_provider_that_returns_success_after_cancellation() -> None:
    started = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()

    async def obsolete_provider() -> str:
        with classification_stage("jev", "request"):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return "obsolete success"

    call = asyncio.create_task(run_classification(obsolete_provider, operation="eot", timeout_s=1,
        telemetry=telemetry, generation=1, attributes={}, executor=executor))
    await started.wait()
    assert await executor.close() == 0
    with pytest.raises(asyncio.CancelledError):
        await call
    assert len(records) == 1
    assert records[0].name == "provider.eot_classifier.classify"
    assert records[0].outcome is TelemetryOutcome.CANCELLED
    assert records[0].attributes["ttfb_ms"] is None


async def test_close_ends_owner_wait_while_uncooperative_provider_remains_tracked() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)
    telemetry, records = recording_telemetry()

    async def obsolete_provider() -> str:
        with classification_stage("jev", "request"):
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            return "obsolete success"

    call = asyncio.create_task(run_classification(obsolete_provider, operation="eot", timeout_s=10,
        telemetry=telemetry, generation=1, attributes={}, executor=executor))
    try:
        await started.wait()
        assert await executor.close(timeout_s=0.001) == 1
        assert call.done(), "closing execution must end its caller's wait as well"
        with pytest.raises(asyncio.CancelledError):
            await call
        assert executor.pending_count == 1
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(records) == 1
        assert records[0].outcome is TelemetryOutcome.CANCELLED
        assert records[0].attributes["ttfb_ms"] is None
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        assert await executor.close() == 0


async def test_close_does_not_cancel_a_caller_that_already_left_classification() -> None:
    timed_out = asyncio.Event()
    finish_caller = asyncio.Event()
    release = asyncio.Event()
    executor = ClassificationExecutor(max_pending=1)

    async def obsolete_provider() -> str:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return "obsolete success"

    async def caller() -> str:
        with pytest.raises(TimeoutError):
            await executor.run(obsolete_provider, timeout_s=0.01)
        timed_out.set()
        await finish_caller.wait()
        return "subsequent work"

    call = asyncio.create_task(caller())
    try:
        await timed_out.wait()
        assert await executor.close(timeout_s=0.001) == 1
        assert not call.cancelling(), "cleanup may cancel only a still-waiting owner"
        finish_caller.set()
        assert await call == "subsequent work"
    finally:
        release.set()
        finish_caller.set()
        await asyncio.gather(call, return_exceptions=True)
        assert await executor.close() == 0
