import array

from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.turn_policy.signals import Signal

SAMPLE_RATE_HZ = 16000


def _chunk(amplitude: int, *, duration_ms: float = 100.0) -> bytes:
    sample_count = int(SAMPLE_RATE_HZ * duration_ms / 1000)
    return array.array("h", [amplitude] * sample_count).tobytes()


def _vad(
    silence_duration_ms: float = 200.0,
    energy_threshold: float = 500.0,
    hesitation_silence_ms: float | None = None,
) -> EnergyVad:
    config = EnergyVadConfig(
        energy_threshold=energy_threshold,
        silence_duration_ms=silence_duration_ms,
        hesitation_silence_ms=hesitation_silence_ms,
    )
    return EnergyVad(config)


def test_empty_chunk_returns_none():
    vad = _vad()

    assert vad.process_chunk(b"", sample_rate_hz=SAMPLE_RATE_HZ) is None


def test_loud_chunk_from_idle_emits_speech_onset():
    vad = _vad()

    signal = vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_SPEECH_ONSET


def test_repeated_loud_chunks_emit_onset_only_once():
    vad = _vad()

    first = vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    second = vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    assert first is Signal.USER_SPEECH_ONSET
    assert second is None


def test_silence_before_any_speech_emits_nothing():
    vad = _vad()

    signal = vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is None


def test_silence_shorter_than_threshold_emits_nothing():
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is None


def test_silence_reaching_threshold_emits_eot_confirmed():
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_EOT_CONFIRMED


def test_eot_observation_reports_the_accumulated_silence_latency() -> None:
    vad = _vad(silence_duration_ms=200.0)
    vad.observe_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.observe_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    observation = vad.observe_chunk(
        _chunk(0, duration_ms=100.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )

    assert observation is not None
    assert observation.signal is Signal.USER_EOT_CONFIRMED
    assert observation.silence_ms == 200.0


def test_new_speech_after_eot_emits_onset_again():
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_SPEECH_ONSET


def test_loud_chunk_resets_accumulated_silence():
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is None


def test_silence_past_hesitation_threshold_emits_hesitation():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=300.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_HESITATION


def test_hesitation_is_emitted_only_once_while_silence_continues():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=300.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=100.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is None


def test_silence_still_reaches_eot_past_full_threshold_after_hesitation():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=300.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=250.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_EOT_CONFIRMED


def test_loud_chunk_after_hesitation_emits_resumed_not_onset():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=300.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_RESUMED


def test_resuming_clears_hesitation_so_a_later_pause_can_hesitate_again():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=300.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is Signal.USER_HESITATION


def test_hesitation_silence_ms_none_never_emits_hesitation():
    vad = _vad(silence_duration_ms=600.0, hesitation_silence_ms=None)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)

    signal = vad.process_chunk(_chunk(0, duration_ms=350.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert signal is None


def test_measure_chunk_reports_loudness_and_duration_without_mutating_state():
    vad = _vad()

    measurement = vad.measure_chunk(_chunk(10_000, duration_ms=250.0), sample_rate_hz=SAMPLE_RATE_HZ)

    assert measurement is not None
    assert measurement.is_loud is True
    assert measurement.duration_ms == 250.0
    # measure_chunk is a pure read: the onset/EoT state machine is untouched.
    assert vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_SPEECH_ONSET


def test_measure_chunk_on_empty_bytes_returns_none():
    vad = _vad()

    assert vad.measure_chunk(b"", sample_rate_hz=SAMPLE_RATE_HZ) is None


def test_resume_user_utterance_lets_silence_alone_reach_eot_again():
    """The mechanism behind ADR-0037's fix for the deferred-EOT deadlock.

    `process_chunk` commits `_speaking = False` as a side effect of returning
    USER_EOT_CONFIRMED, so a caller that declines the signal is left unable to
    ever get another one from silence alone. After re-arming, a fresh
    silence_duration_ms of quiet must produce a second USER_EOT_CONFIRMED with
    no further speech from the user.
    """
    vad = _vad(silence_duration_ms=200.0)
    assert vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_SPEECH_ONSET
    assert vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is None
    assert (
        vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_EOT_CONFIRMED
    )

    # Without this the two quiet chunks below yield nothing, forever.
    vad.resume_user_utterance()

    assert vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is None
    assert (
        vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_EOT_CONFIRMED
    )


def test_resume_user_utterance_grants_a_full_fresh_silence_window():
    """Re-arming resets the accumulated silence rather than restoring it, so the
    next EoT is a genuine new timeout instead of firing on the very next chunk."""
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ)

    vad.resume_user_utterance()

    assert vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is None


def test_loud_chunk_after_resume_is_not_a_fresh_onset():
    """The continuation of one utterance must not read as a new turn — this is
    what keeps a deferred EoT's utterance on a single generation."""
    vad = _vad(silence_duration_ms=200.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ)
    vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ)

    vad.resume_user_utterance()

    assert vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ) is None


def test_resume_user_utterance_clears_hesitation_so_it_can_fire_again():
    """`_hesitated` must be cleared too. On the barge-in path the tracker is
    never advanced during SPEAK/DUAL (those only call `measure_chunk`), so a
    stale True would make the next loud chunk emit USER_RESUMED instead of
    continuing the utterance silently."""
    vad = _vad(silence_duration_ms=400.0, hesitation_silence_ms=100.0)
    vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ)
    assert vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_HESITATION

    vad.resume_user_utterance()

    # Not USER_RESUMED: as far as the tracker is concerned this utterance never
    # paused.
    assert vad.process_chunk(_chunk(10_000), sample_rate_hz=SAMPLE_RATE_HZ) is None
    assert vad.process_chunk(_chunk(0), sample_rate_hz=SAMPLE_RATE_HZ) is Signal.USER_HESITATION
