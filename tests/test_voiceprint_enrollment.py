import pytest

from server.voiceprint.enrollment import (
    AdaptiveEnrollment,
    VoiceprintEnrollmentError,
    enroll_recording,
)
from server.voiceprint.matching import InMemoryVoiceprintRepository


class FakeEmbedder:
    def __init__(self, embeddings: list[list[float] | None]) -> None:
        self._embeddings = list(embeddings)

    async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None:
        return self._embeddings.pop(0)


def _pcm16(sample_count: int) -> bytes:
    return b"\x00\x00" * sample_count


async def test_enroll_recording_activates_a_profile():
    embedder = FakeEmbedder([[1.0, 0.0]])
    repository = InMemoryVoiceprintRepository()

    profile = await enroll_recording(
        embedder,
        _pcm16(10),
        sample_rate_hz=1000,
        display_name="Alex",
        repository=repository,
    )

    assert profile.centroid == [1.0, 0.0]
    assert profile.display_name == "Alex"
    assert await repository.get_active_profile() == profile


async def test_enroll_recording_uses_given_profile_id():
    embedder = FakeEmbedder([[1.0, 0.0]])
    repository = InMemoryVoiceprintRepository()

    profile = await enroll_recording(
        embedder,
        _pcm16(10),
        sample_rate_hz=1000,
        display_name="Alex",
        repository=repository,
        profile_id="fixed-id",
    )

    assert profile.profile_id == "fixed-id"


async def test_enroll_recording_raises_when_embedding_fails():
    embedder = FakeEmbedder([None])
    repository = InMemoryVoiceprintRepository()

    with pytest.raises(VoiceprintEnrollmentError):
        await enroll_recording(
            embedder,
            _pcm16(10),
            sample_rate_hz=1000,
            display_name="Alex",
            repository=repository,
        )
    assert await repository.get_active_profile() is None


async def test_adaptive_enrollment_stays_in_progress_before_target_turns():
    embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0]])
    repository = InMemoryVoiceprintRepository()
    enrollment = AdaptiveEnrollment(
        embedder, repository, display_name="Alex", target_turns=3
    )

    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)

    assert enrollment.is_in_progress is True
    assert await repository.get_active_profile() is None


async def test_adaptive_enrollment_activates_after_target_turns():
    embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
    repository = InMemoryVoiceprintRepository()
    enrollment = AdaptiveEnrollment(
        embedder, repository, display_name="Alex", target_turns=3
    )

    for _ in range(3):
        await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.wait_until_activated()

    assert enrollment.is_in_progress is False
    profile = await repository.get_active_profile()
    assert profile is not None
    assert profile.display_name == "Alex"
    assert profile.centroid == pytest.approx([1.0, 0.0])


async def test_adaptive_enrollment_ignores_a_failed_embedding():
    embedder = FakeEmbedder([[1.0, 0.0], None, [1.0, 0.0]])
    repository = InMemoryVoiceprintRepository()
    enrollment = AdaptiveEnrollment(
        embedder, repository, display_name="Alex", target_turns=2
    )

    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)  # embedding fails, not counted
    assert enrollment.is_in_progress is True

    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.wait_until_activated()

    assert enrollment.is_in_progress is False


async def test_adaptive_enrollment_keeps_dominant_cluster_by_duration():
    # Four samples: three long, near [1, 0] samples (the real speaker) and
    # one short, far-away [0, 1] sample (an incidental interjection). The
    # dominant cluster by total duration should win even though it isn't
    # the numerical majority-by-count in a tie-breaking sense.
    embeddings = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    embedder = FakeEmbedder(list(embeddings))
    repository = InMemoryVoiceprintRepository()
    enrollment = AdaptiveEnrollment(
        embedder, repository, display_name="Alex", target_turns=4
    )

    await enrollment.observe_turn(_pcm16(100), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(100), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(100), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(5), sample_rate_hz=1000)
    await enrollment.wait_until_activated()

    profile = await repository.get_active_profile()
    assert profile.centroid == pytest.approx([1.0, 0.0])


async def test_adaptive_enrollment_ignores_further_turns_once_done():
    embedder = FakeEmbedder([[1.0, 0.0], [1.0, 0.0], [9.0, 9.0]])
    repository = InMemoryVoiceprintRepository()
    enrollment = AdaptiveEnrollment(
        embedder, repository, display_name="Alex", target_turns=2
    )

    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)
    await enrollment.wait_until_activated()
    await enrollment.observe_turn(_pcm16(10), sample_rate_hz=1000)

    profile = await repository.get_active_profile()
    assert profile.centroid == pytest.approx([1.0, 0.0])
