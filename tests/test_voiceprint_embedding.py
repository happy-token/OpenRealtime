from server.voiceprint.embedding import PreloadedSpeakerEmbedder


async def test_preloaded_speaker_embedder_returns_fixed_embedding():
    embedder = PreloadedSpeakerEmbedder([0.1, 0.2, 0.3])

    embedding = await embedder.embed(b"\x00\x00" * 100, sample_rate_hz=16000)

    assert embedding == [0.1, 0.2, 0.3]


async def test_preloaded_speaker_embedder_ignores_input_audio():
    embedder = PreloadedSpeakerEmbedder([0.5, 0.5])

    first = await embedder.embed(b"\x01\x02", sample_rate_hz=8000)
    second = await embedder.embed(b"\x03\x04\x05\x06", sample_rate_hz=16000)

    assert first == second == [0.5, 0.5]


async def test_preloaded_speaker_embedder_can_simulate_a_failure():
    embedder = PreloadedSpeakerEmbedder(None)

    embedding = await embedder.embed(b"\x00\x00", sample_rate_hz=16000)

    assert embedding is None
