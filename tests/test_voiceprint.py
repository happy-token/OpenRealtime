from server.core.turn_content import VoiceprintResult
from server.signals.voiceprint import NoVoiceprintMatching


class StubVoiceprintMatcher:
    """Test double: always returns a fixed VoiceprintResult."""

    def __init__(self, result: VoiceprintResult) -> None:
        self._result = result

    async def match(self, *, generation: int) -> VoiceprintResult | None:
        return self._result

    async def add_audio(self, pcm16: bytes, *, sample_rate_hz: int, generation: int) -> None:
        return None


async def test_no_voiceprint_matching_returns_none():
    matcher = NoVoiceprintMatching()

    result = await matcher.match(generation=1)

    assert result is None


async def test_no_voiceprint_matching_add_audio_is_a_no_op():
    matcher = NoVoiceprintMatching()

    result = await matcher.add_audio(b"\x00\x00", sample_rate_hz=16000, generation=1)

    assert result is None


async def test_stub_matcher_returns_match():
    matcher = StubVoiceprintMatcher("match")

    assert await matcher.match(generation=1) == "match"


async def test_stub_matcher_returns_no_match():
    matcher = StubVoiceprintMatcher("no_match")

    assert await matcher.match(generation=1) == "no_match"


async def test_stub_matcher_returns_unavailable():
    matcher = StubVoiceprintMatcher("unavailable")

    assert await matcher.match(generation=1) == "unavailable"


async def test_stub_matcher_returns_adaptive():
    matcher = StubVoiceprintMatcher("adaptive")

    assert await matcher.match(generation=1) == "adaptive"
