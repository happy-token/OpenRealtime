import pytest

from server.ledger.event_ledger import EventLedger, LedgerEvent


async def test_emit_with_no_observers_does_not_raise():
    ledger = EventLedger()

    await ledger.emit("turn.started", generation=1)


async def test_subscribed_observer_receives_emitted_event():
    ledger = EventLedger()
    received: list[LedgerEvent] = []

    async def observer(event: LedgerEvent) -> None:
        received.append(event)

    ledger.subscribe(observer)
    await ledger.emit("turn.started", generation=3, turn_id="abc")

    assert len(received) == 1
    assert received[0].name == "turn.started"
    assert received[0].generation == 3
    assert received[0].payload == {"turn_id": "abc"}


async def test_failing_observer_does_not_prevent_other_observers_or_raise():
    ledger = EventLedger()
    received: list[str] = []

    async def broken_observer(event: LedgerEvent) -> None:
        raise RuntimeError("boom")

    async def healthy_observer(event: LedgerEvent) -> None:
        received.append(event.name)

    ledger.subscribe(broken_observer)
    ledger.subscribe(healthy_observer)

    await ledger.emit("turn.ended", generation=1)

    assert received == ["turn.ended"]


@pytest.mark.asyncio
async def test_multiple_observers_all_receive_the_same_event():
    ledger = EventLedger()
    counts = {"a": 0, "b": 0}

    async def observer_a(event: LedgerEvent) -> None:
        counts["a"] += 1

    async def observer_b(event: LedgerEvent) -> None:
        counts["b"] += 1

    ledger.subscribe(observer_a)
    ledger.subscribe(observer_b)
    await ledger.emit("phase.changed", generation=1)

    assert counts == {"a": 1, "b": 1}
