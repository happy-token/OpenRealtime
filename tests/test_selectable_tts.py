from collections.abc import AsyncIterator, Callable

from server.speech.selectable_tts import SelectableTtsEngine
from server.speech.tts import SynthesizedAudio, SynthesizedAudioChunk, TtsSessionConfig


class _FakeTts:
    def __init__(self, provider: str, config: TtsSessionConfig) -> None:
        self.provider = provider
        self.config = config
        self.closed = False
        self.calls: list[str] = []

    async def synthesize(self, text: str) -> SynthesizedAudio:
        self.calls.append(text)
        return SynthesizedAudio(pcm16=self.provider.encode(), sample_rate_hz=24_000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        audio = await self.synthesize(text)
        yield SynthesizedAudioChunk(
            pcm16=audio.pcm16,
            sample_rate_hz=audio.sample_rate_hz,
            is_final=True,
        )

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        text = "".join([part async for part in text_stream])
        async for chunk in self.synthesize_stream(text):
            yield chunk

    async def close(self) -> None:
        self.closed = True


def _factory(provider: str, created: list[_FakeTts]) -> Callable[[TtsSessionConfig], _FakeTts]:
    def build(config: TtsSessionConfig) -> _FakeTts:
        engine = _FakeTts(provider, config)
        created.append(engine)
        return engine

    return build


async def test_selectable_tts_routes_new_speech_to_the_selected_provider() -> None:
    created: list[_FakeTts] = []
    engine = SelectableTtsEngine(
        factories={
            "bailian": _factory("bailian", created),
            "doubao": _factory("doubao", created),
        },
        provider="bailian",
        config=TtsSessionConfig(voice="longanhuan_v3"),
    )

    first = await engine.synthesize("百炼")
    await engine.select(
        "doubao",
        TtsSessionConfig(voice="zh_female_vv_uranus_bigtts", dialect="dongbei"),
    )
    second = await engine.synthesize("火山")

    assert first.pcm16 == b"bailian"
    assert second.pcm16 == b"doubao"
    assert created[0].closed is True
    assert engine.provider == "doubao"
    assert created[1].config.dialect == "dongbei"


async def test_selectable_tts_reuses_engine_when_selection_is_unchanged() -> None:
    created: list[_FakeTts] = []
    config = TtsSessionConfig(voice="longanhuan_v3")
    engine = SelectableTtsEngine(
        factories={"bailian": _factory("bailian", created)},
        provider="bailian",
        config=config,
    )

    await engine.select("bailian", config)

    assert len(created) == 1
    assert created[0].closed is False
