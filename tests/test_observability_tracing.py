import asyncio
import logging

import pytest

from server.ledger.event_ledger import EventLedger
from server.observability.tracing import StageTracer


async def test_span_success_logs_ok_and_returns_normally(caplog):
    tracer = StageTracer("session-1")

    with caplog.at_level(logging.INFO):
        async with tracer.span("stage.name", generation=1):
            pass

    record = caplog.records[-1]
    assert record.levelno == logging.INFO
    assert "status=ok" in record.message
    assert "stage=stage.name" in record.message
    assert "session=session-1" in record.message
    assert "generation=1" in record.message


async def test_span_error_logs_error_with_traceback_and_reraises(caplog):
    tracer = StageTracer("session-1")

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        async with tracer.span("stage.name", generation=1):
            raise ValueError("boom")

    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert "status=error" in record.message
    assert "ValueError: boom" in record.message
    assert record.exc_info is not None


async def test_span_cancelled_logs_cancelled_and_reraises(caplog):
    tracer = StageTracer("session-1")

    with caplog.at_level(logging.INFO), pytest.raises(asyncio.CancelledError):
        async with tracer.span("stage.name", generation=1):
            raise asyncio.CancelledError()

    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "status=cancelled" in record.message


async def test_span_timeout_logs_timeout_and_reraises(caplog):
    tracer = StageTracer("session-1")

    with caplog.at_level(logging.INFO), pytest.raises(TimeoutError):
        async with tracer.span("stage.name", generation=1):
            raise TimeoutError("too slow")

    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "status=timeout" in record.message
    assert "TimeoutError: too slow" in record.message


async def test_span_emits_ledger_event_when_generation_given():
    ledger = EventLedger()
    events = []

    async def observer(event):
        events.append(event)

    ledger.subscribe(observer)
    tracer = StageTracer("session-1", ledger=ledger)

    async with tracer.span("stage.name", generation=7, foo="bar"):
        pass

    assert len(events) == 1
    assert events[0].name == "stage_span"
    assert events[0].generation == 7
    assert events[0].payload["stage"] == "stage.name"
    assert events[0].payload["status"] == "ok"
    assert events[0].payload["foo"] == "bar"
    assert "duration_ms" in events[0].payload


async def test_span_skips_ledger_emit_when_generation_is_none():
    ledger = EventLedger()
    events = []

    async def observer(event):
        events.append(event)

    ledger.subscribe(observer)
    tracer = StageTracer("session-1", ledger=ledger)

    async with tracer.span("stage.name", generation=None):
        pass

    assert events == []


def test_sync_span_success_logs_ok(caplog):
    tracer = StageTracer("session-1")

    with caplog.at_level(logging.INFO), tracer.sync_span("hook.name", generation=2):
        pass

    record = caplog.records[-1]
    assert record.levelno == logging.INFO
    assert "status=ok" in record.message
    assert "stage=hook.name" in record.message


def test_sync_span_error_logs_error_and_reraises(caplog):
    tracer = StageTracer("session-1")

    with (
        caplog.at_level(logging.INFO),
        pytest.raises(ValueError),
        tracer.sync_span("hook.name", generation=2),
    ):
        raise ValueError("boom")

    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert "status=error" in record.message
