import asyncio

from server.turn_policy.semantic_task_registry import SemanticTaskRegistry


def test_stale_result_cannot_consume_current_token_and_accept_is_once():
    tasks = SemanticTaskRegistry()
    tasks.register('endpoint', 'chunk', 'current')
    assert not tasks.accept('endpoint', 'chunk', 'old')
    assert tasks.accept('endpoint', 'chunk', 'current')
    assert not tasks.accept('endpoint', 'chunk', 'current')


async def test_cancel_family_invalidates_tokens_without_cancelling_other_families():
    tasks = SemanticTaskRegistry()
    async def wait():
        await asyncio.Event().wait()
    tasks.register('endpoint', 'one', 'e')
    tasks.register('interruption', 'two', 'i')
    tasks.start('endpoint_model:one', wait())
    tasks.start('interruption_model:two', wait())
    tasks.cancel('endpoint_model')
    assert not tasks.accept('endpoint', 'one', 'e')
    assert tasks.accept('interruption', 'two', 'i')
    assert 'interruption_model:two' in tasks.jobs
    active = list(tasks.all_tasks)
    tasks.clear()
    await asyncio.gather(*active, return_exceptions=True)
    assert tasks.jobs == {}


async def test_completed_chunk_jobs_do_not_accumulate_or_consume_queued_results():
    tasks = SemanticTaskRegistry()

    async def finish():
        return

    tasks.start('commit', finish())
    tasks.start('recovery', finish())
    for number in range(300):
        chunk_id = str(number)
        tasks.register('endpoint', chunk_id, chunk_id)
        tasks.start('endpoint_model:' + chunk_id, finish())
        await asyncio.gather(*tasks.all_tasks)
        await asyncio.sleep(0)
        # Completion removes execution metadata, not the actor's queued result token.
        assert tasks.accept('endpoint', chunk_id, chunk_id)

    assert set(tasks.jobs) == {'commit', 'recovery'}
    assert tasks.all_tasks == set()


async def test_cancel_family_invalidates_completed_chunk_results_waiting_for_actor():
    tasks = SemanticTaskRegistry()

    async def finish():
        return

    tasks.register('endpoint', 'one', 'e')
    tasks.register('interruption', 'two', 'i')
    tasks.start('endpoint_model:one', finish())
    tasks.start('interruption_model:two', finish())
    await asyncio.gather(*tasks.all_tasks)
    await asyncio.sleep(0)
    tasks.cancel('endpoint_model')
    assert not tasks.accept('endpoint', 'one', 'e')
    assert tasks.accept('interruption', 'two', 'i')


async def test_old_chunk_done_callback_cannot_remove_replacement_task():
    tasks = SemanticTaskRegistry()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def ignore_cancellation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    async def wait():
        await asyncio.Event().wait()

    tasks.start('endpoint_model:one', ignore_cancellation())
    old_task = tasks.jobs['endpoint_model:one']
    await asyncio.sleep(0)
    tasks.start('endpoint_model:one', wait())
    new_task = tasks.jobs['endpoint_model:one']
    await cancelled.wait()
    release.set()
    await old_task
    await asyncio.sleep(0)
    assert tasks.jobs['endpoint_model:one'] is new_task
    tasks.clear()
    await asyncio.gather(new_task, return_exceptions=True)
