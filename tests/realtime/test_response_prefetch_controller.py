import asyncio

import pytest

from server.realtime.capabilities.response_prefetch_controller import (
    PrefetchCandidate,
    ResponsePrefetchController,
)


class Provider:
    def __init__(self):
        self.prepared = []
        self.invalidated = []
        self.ready = asyncio.Event()

    async def prepare(self, turn):
        self.prepared.append(turn)
        self.ready.set()
        return True

    async def invalidate(self, generation, *, reason):
        self.invalidated.append((generation, reason))


def candidate(text="查天气。", **changes):
    return PrefetchCandidate(
        identity="input", generation=1, text=text, revision=1, speech_active=True,
        **changes,
    )


@pytest.mark.asyncio
async def test_deduplicates_stable_candidate_and_keeps_cache_for_matching_commit():
    provider = Provider()
    controller = ResponsePrefetchController(provider, enabled=True, is_current=lambda _: True)
    controller.prepare(candidate())
    await provider.ready.wait()
    controller.prepare(candidate())
    controller.finalize("查天气。", 1)
    await asyncio.sleep(0)
    assert len(provider.prepared) == 1
    assert provider.invalidated == []
    await controller.close()
    assert provider.invalidated == [(1, "session_closed")]


@pytest.mark.asyncio
async def test_revision_cleanup_finishes_before_replacement_prepare():
    provider = Provider()
    controller = ResponsePrefetchController(provider, enabled=True, is_current=lambda _: True)
    controller.prepare(candidate())
    await provider.ready.wait()
    controller.observe_text("查上海天气。")
    controller.prepare(candidate("查上海天气。"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert provider.invalidated == [(1, "asr_revision")]
    assert [turn.text for turn in provider.prepared] == ["查天气。", "查上海天气。"]
    await controller.close()


@pytest.mark.asyncio
async def test_ineligible_inputs_and_stale_builder_never_start_model():
    provider = Provider()
    controller = ResponsePrefetchController(provider, enabled=True, is_current=lambda _: False)
    controller.prepare(candidate("还没说完"))
    controller.prepare(candidate(interrupted=True))
    controller.prepare(candidate(continuation=True))
    controller.prepare(candidate(committed=True))
    controller.prepare(candidate())
    await asyncio.sleep(0)
    assert provider.prepared == []
    await controller.close()
    assert provider.invalidated == []
