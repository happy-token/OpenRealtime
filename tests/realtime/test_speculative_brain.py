from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain


class EmptyOnceBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        del turn
        self.calls += 1
        if self.calls == 1:
            return
        yield "重试后的有效回复"


@pytest.mark.asyncio
async def test_empty_speculative_response_retries_at_commit_boundary() -> None:
    provider = EmptyOnceBrain()
    brain = SpeculativeStreamingBrain(provider)
    turn = TurnContent(text="你好", generation=1)

    assert await brain.prepare(turn) is True

    assert [delta async for delta in brain.stream(turn)] == ["重试后的有效回复"]
    assert provider.calls == 2
