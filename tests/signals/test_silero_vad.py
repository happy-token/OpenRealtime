from __future__ import annotations

import array

import pytest

from server.signals.energy_vad import EnergyVadConfig
from server.signals.plugins.silero_vad import SileroVad
from server.turn_policy.signals import Signal


class Scalar:
    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value


class FakeSileroModel:
    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = probabilities
        self.calls: list[tuple[tuple[float, ...], int]] = []
        self.reset_count = 0

    def __call__(self, samples: tuple[float, ...], sample_rate_hz: int) -> Scalar:
        self.calls.append((samples, sample_rate_hz))
        return Scalar(self.probabilities.pop(0))

    def reset_states(self) -> None:
        self.reset_count += 1


def pcm(sample_count: int, amplitude: int = 1000) -> bytes:
    return array.array("h", [amplitude] * sample_count).tobytes()


def vad(
    model: FakeSileroModel,
    *,
    silence_ms: float = 64,
    speech_onset_ms: float = 0,
) -> SileroVad:
    return SileroVad(
        EnergyVadConfig(
            silence_duration_ms=silence_ms,
            speech_onset_duration_ms=speech_onset_ms,
        ),
        model=model,
        tensor_factory=lambda values: tuple(values),
    )


def test_direct_silero_model_receives_normalized_official_16khz_windows() -> None:
    model = FakeSileroModel([0.9])
    detector = vad(model)

    measurement = detector.measure_chunk(pcm(512, amplitude=16384), sample_rate_hz=16000)

    assert measurement is not None
    assert measurement.is_loud is True
    assert measurement.duration_ms == 32
    samples, sample_rate = model.calls[0]
    assert sample_rate == 16000
    assert len(samples) == 512
    assert samples[0] == 0.5


def test_short_chunks_are_bounded_until_one_official_model_window_exists() -> None:
    model = FakeSileroModel([0.8])
    detector = vad(model)

    assert detector.measure_chunk(pcm(160), sample_rate_hz=16000) is None
    assert detector.measure_chunk(pcm(160), sample_rate_hz=16000) is None
    measurement = detector.measure_chunk(pcm(192), sample_rate_hz=16000)

    assert measurement is not None
    assert measurement.duration_ms == 32
    assert len(model.calls) == 1


def test_empty_chunk_does_not_load_or_call_the_model() -> None:
    model = FakeSileroModel([0.8])
    detector = vad(model)

    assert detector.measure_chunk(b"", sample_rate_hz=16000) is None
    assert model.calls == []


def test_direct_probabilities_drive_voiceagent_onset_and_eot_tracker() -> None:
    model = FakeSileroModel([0.9, 0.1, 0.1])
    detector = vad(model, silence_ms=64)

    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is Signal.USER_SPEECH_ONSET
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is Signal.USER_EOT_CONFIRMED


def test_sustained_onset_rejects_one_isolated_speech_probability_spike() -> None:
    model = FakeSileroModel([0.9, 0.1, 0.9, 0.9, 0.9])
    detector = vad(model, speech_onset_ms=96)

    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is Signal.USER_SPEECH_ONSET


@pytest.mark.parametrize(
    ("silence_ms", "quiet_chunks_before_eot"),
    [(300, 4), (200, 3)],
)
def test_eot_window_at_browser_100ms_chunk_cadence(
    silence_ms: float,
    quiet_chunks_before_eot: int,
) -> None:
    # Each browser worklet chunk contains roughly three 32ms Silero windows.
    model = FakeSileroModel([0.9] * 3 + [0.1] * (quiet_chunks_before_eot * 4))
    detector = vad(model, silence_ms=silence_ms)

    assert detector.process_chunk(pcm(1600), sample_rate_hz=16000) is Signal.USER_SPEECH_ONSET
    for _ in range(quiet_chunks_before_eot - 1):
        assert detector.process_chunk(pcm(1600), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(1600), sample_rate_hz=16000) is Signal.USER_EOT_CONFIRMED


def test_32ms_local_packets_expose_256ms_silero_eot_at_256ms() -> None:
    # Eight exact Silero windows expose the configured 256ms without either
    # model-window or network-packet rounding.
    model = FakeSileroModel([0.9] + [0.1] * 8)
    detector = vad(model, silence_ms=256)

    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is Signal.USER_SPEECH_ONSET
    for _ in range(7):
        assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is None
    assert detector.process_chunk(pcm(512), sample_rate_hz=16000) is Signal.USER_EOT_CONFIRMED


def test_sample_rate_change_resets_model_state_and_pending_audio() -> None:
    model = FakeSileroModel([0.9])
    detector = vad(model)
    assert detector.measure_chunk(pcm(200), sample_rate_hz=16000) is None

    measurement = detector.measure_chunk(pcm(256), sample_rate_hz=8000)

    assert measurement is not None
    assert model.reset_count == 1
    assert model.calls[0][1] == 8000


def test_unsupported_sample_rate_fails_explicitly() -> None:
    detector = vad(FakeSileroModel([]))

    with pytest.raises(ValueError, match="8000 or 16000"):
        detector.measure_chunk(pcm(512), sample_rate_hz=24000)


def test_invalid_threshold_fails_during_construction() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        SileroVad(threshold=1.0)


def test_invalid_model_probability_fails_explicitly() -> None:
    detector = vad(FakeSileroModel([float("nan")]))

    with pytest.raises(ValueError, match="invalid speech probability"):
        detector.measure_chunk(pcm(512), sample_rate_hz=16000)


def test_close_discards_pending_audio_and_resets_model_state() -> None:
    model = FakeSileroModel([0.9])
    detector = vad(model)
    assert detector.measure_chunk(pcm(200), sample_rate_hz=16000) is None

    detector.close()

    assert model.reset_count == 1
    assert detector.measure_chunk(pcm(312), sample_rate_hz=16000) is None
