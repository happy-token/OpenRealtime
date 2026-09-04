import asyncio

from server.agent_session.in_memory_session import InMemoryDriver
from server.core.turn_content import TurnContent


async def test_send_turn_stores_content():
    session = InMemoryDriver().create_session()

    await session.send_turn(TurnContent(text="find flights", generation=1))

    assert session.sent_content == TurnContent(text="find flights", generation=1)


async def test_result_blocks_until_resolve():
    session = InMemoryDriver().create_session()
    result_task = asyncio.ensure_future(session.result())
    await asyncio.sleep(0)
    assert not result_task.done()

    session.resolve("done")

    outcome = await result_task
    assert outcome.ok is True
    assert outcome.text == "done"
    assert outcome.error is None


async def test_result_blocks_until_fail():
    session = InMemoryDriver().create_session()
    result_task = asyncio.ensure_future(session.result())
    await asyncio.sleep(0)
    assert not result_task.done()

    session.fail("backend unreachable")

    outcome = await result_task
    assert outcome.ok is False
    assert outcome.error == "backend unreachable"
    assert outcome.text is None


async def test_latest_update_reflects_push_update():
    session = InMemoryDriver().create_session()

    assert await session.latest_update() is None

    session.push_update("still searching...")

    update = await session.latest_update()
    assert update is not None
    assert update.text == "still searching..."


async def test_cancel_marks_cancelled():
    session = InMemoryDriver().create_session()

    assert session.cancelled is False

    await session.cancel()

    assert session.cancelled is True


async def test_driver_creates_fresh_independent_sessions():
    driver = InMemoryDriver()

    first = driver.create_session()
    second = driver.create_session()

    first.resolve("first result")

    assert first is not second
    assert driver.sessions == [first, second]
    assert (await second.latest_update()) is None
