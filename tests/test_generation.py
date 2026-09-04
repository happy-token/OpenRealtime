from server.core.generation import GenerationCounter


def test_new_counter_starts_at_zero():
    counter = GenerationCounter()

    assert counter.current == 0


def test_advance_increments_and_returns_new_value():
    counter = GenerationCounter()

    first = counter.advance()
    second = counter.advance()

    assert first == 1
    assert second == 2
    assert counter.current == 2


def test_lease_is_current_when_generation_unchanged():
    counter = GenerationCounter()
    counter.advance()

    lease = counter.lease()

    assert lease.is_current()


def test_lease_becomes_stale_once_counter_advances_again():
    counter = GenerationCounter()
    lease = counter.lease()

    counter.advance()

    assert not lease.is_current()
