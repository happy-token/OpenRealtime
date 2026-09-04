from server.signals.vision_source import NoVisionSource


class StubVisionSource:
    """Test double: always returns a fixed vision description."""

    def __init__(self, description: str) -> None:
        self._description = description

    async def describe(self, *, generation: int) -> str | None:
        return self._description


async def test_no_vision_source_returns_none():
    source = NoVisionSource()

    result = await source.describe(generation=1)

    assert result is None


async def test_stub_vision_source_returns_description():
    source = StubVisionSource("a red mug on a desk")

    assert await source.describe(generation=1) == "a red mug on a desk"
