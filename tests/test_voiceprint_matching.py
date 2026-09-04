import pytest

from server.voiceprint.matching import (
    EnrolledSpeakerVoiceprintMatcher,
    InMemoryVoiceprintRepository,
    VoiceprintProfile,
    cosine_distance,
)


class FakeEmbedder:
    def __init__(self, embedding: list[float] | None) -> None:
        self._embedding = embedding
        self.calls = 0

    async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None:
        self.calls += 1
        return self._embedding


def _pcm16(sample_count: int) -> bytes:
    return b"\x00\x00" * sample_count


def test_cosine_distance_of_identical_vectors_is_zero():
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_cosine_distance_of_orthogonal_vectors_is_one():
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_cosine_distance_of_opposite_vectors_is_two():
    assert cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)


@pytest.mark.parametrize(
    "a, b",
    [
        ([], [1.0]),
        ([1.0, 0.0], [1.0]),
        ([0.0, 0.0], [1.0, 0.0]),
        ([1.0, 0.0], [0.0, 0.0]),
    ],
)
def test_cosine_distance_of_degenerate_inputs_is_maximally_distant(a, b):
    assert cosine_distance(a, b) == 1.0


async def test_in_memory_repository_has_no_active_profile_initially():
    repository = InMemoryVoiceprintRepository()

    assert await repository.get_active_profile() is None


async def test_in_memory_repository_upsert_and_activate():
    repository = InMemoryVoiceprintRepository()
    profile = VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])

    await repository.upsert_profile(profile)
    await repository.set_active_profile("p1")

    assert await repository.get_active_profile() == profile


async def test_in_memory_repository_activating_unknown_profile_raises():
    repository = InMemoryVoiceprintRepository()

    with pytest.raises(KeyError):
        await repository.set_active_profile("missing")


async def test_add_audio_does_not_cache_before_min_audio_ms_reached():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=1000.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result is None
    assert embedder.calls == 0


async def test_add_audio_eagerly_caches_once_min_audio_ms_reached():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=10.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result == (1, "match")
    assert embedder.calls == 1


async def test_add_audio_resets_buffer_on_generation_change():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=10.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)
    assert matcher.last_result == (1, "match")

    await matcher.add_audio(_pcm16(1), sample_rate_hz=1000, generation=2)
    assert matcher.last_result is None


async def test_match_returns_unavailable_with_no_buffered_audio():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository)

    assert await matcher.match(generation=1) == "unavailable"


async def test_match_returns_unavailable_for_a_stale_generation():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=1000.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert await matcher.match(generation=2) == "unavailable"


async def test_match_computes_from_buffered_audio_below_min_audio_ms():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=1000.0)
    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)
    assert matcher.last_result is None

    assert await matcher.match(generation=1) == "match"


async def test_match_returns_unavailable_when_no_active_profile():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=10.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result == (1, "unavailable")


async def test_match_returns_unavailable_when_embedding_fails():
    embedder = FakeEmbedder(None)
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(embedder, repository, min_audio_ms=10.0)

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result == (1, "unavailable")


async def test_match_returns_no_match_when_distance_exceeds_threshold():
    embedder = FakeEmbedder([0.0, 1.0])
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(
        embedder, repository, min_audio_ms=10.0, distance_threshold=0.5
    )

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result == (1, "no_match")


async def test_match_returns_adaptive_while_enrollment_in_progress():
    embedder = FakeEmbedder([1.0, 0.0])
    repository = InMemoryVoiceprintRepository()
    await repository.upsert_profile(
        VoiceprintProfile(profile_id="p1", display_name="Alex", centroid=[1.0, 0.0])
    )
    await repository.set_active_profile("p1")
    matcher = EnrolledSpeakerVoiceprintMatcher(
        embedder, repository, min_audio_ms=10.0, enrollment_in_progress=lambda: True
    )

    await matcher.add_audio(_pcm16(10), sample_rate_hz=1000, generation=1)

    assert matcher.last_result == (1, "adaptive")
    assert embedder.calls == 0
