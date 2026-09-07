import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

for dependency in ("cv2", "librosa", "av", "aiortc"):
    pytest.importorskip(dependency)

from server.avatar_compositing import CompositionConfig
from server.avatar_compositing.runtime import AvatarFrames, AvatarRenderer, mel_windows
from server.avatar_compositing.service import OutputTrack, RenderSession


def test_stride_two_carries_the_next_keyframe_across_output_batches():
    renderer = AvatarRenderer.__new__(AvatarRenderer)
    renderer.stride = 2
    renderer.config = CompositionConfig(wav2lip_blend=1)
    calls = []

    def predict(faces, windows, *, keyframes_only=False):
        calls.append([int(face[0, 0, 0]) for face in faces])
        assert keyframes_only
        return np.asarray(faces)

    renderer.predict = predict
    faces = [np.full((100, 100, 3), i, dtype=np.uint8) for i in range(12)]
    avatar = AvatarFrames(Path("."), [], faces, [(0, 100, 0, 100)] * 12,
                          [np.zeros_like(faces[0])] * 12)
    carry = {}
    first, _ = renderer.render_batch(avatar, np.zeros((80, 100)), 0, 0, 4, carry)
    second, _ = renderer.render_batch(avatar, np.zeros((80, 100)), 4, 4, 4, carry)
    assert [int(frame[77, 50, 0]) for frame in first + second] == list(range(8))
    assert calls == [[0, 2, 4], [6, 8]]


def test_final_phoneme_window_advances_into_silence_instead_of_repeating():
    mel = np.broadcast_to(np.arange(20, dtype=np.float32), (80, 20))
    windows = mel_windows(mel, 5, 2)
    assert windows.shape == (2, 80, 16)
    assert windows[0, 0, 0] == 16
    assert windows[1, 0, 0] == 19
    assert np.all(windows[1, :, 1:] == -4)


def test_stride_lookahead_past_short_utterance_still_has_a_full_mel_window():
    windows = mel_windows(np.zeros((80, 4)), 2, 1)
    assert windows.shape == (1, 80, 16)
    assert np.all(windows == -4)


@pytest.mark.asyncio
async def test_interrupt_during_playback_wait_discards_the_cancelled_frame():
    session = RenderSession(SimpleNamespace(), SimpleNamespace(), asyncio.Lock(), 4)
    track = OutputTrack(session, "audio")
    session.clock = __import__("time").monotonic()
    await session.audio.put((2, 0, np.ones(640, dtype=np.int16)))
    pending = asyncio.create_task(track.recv())
    await asyncio.sleep(0.01)
    session.interrupt()
    await session.audio.put((3, 1, np.full(640, 2, dtype=np.int16)))
    frame = await asyncio.wait_for(pending, 1)
    assert frame.pts == 3 * 640
    assert np.all(frame.to_ndarray() == 2)


def test_stream_mel_preserves_full_utterance_windows_across_chunk_boundaries():
    from server.avatar_compositing.runtime import mel_spectrogram, stream_mel
    rng = np.random.default_rng(42)
    pcm = rng.integers(-12000, 12000, 16000 * 3, dtype=np.int16)
    full = mel_spectrogram(pcm.astype(np.float32) / 32768)
    for start, count in ((0, 2), (2, 8), (10, 8), (18, 4), (22, 8)):
        local, origin = stream_mel(pcm, start, count)
        np.testing.assert_allclose(mel_windows(local, start, count + 1, origin),
                                   mel_windows(full, start, count + 1), atol=1e-5)


def test_stream_chunks_preserve_samples_without_inserting_frame_padding():
    from server.avatar_compositing.service import SpeechBuffer
    speech = SpeechBuffer(8)
    chunks = [np.arange(5123, dtype=np.int16), np.arange(2999, dtype=np.int16)]
    speech.append(chunks[0], 0, False)
    assert speech.available_frames() == 0  # Retain a small initial jitter reserve.
    speech.offset = 2
    speech.append(chunks[1], 1, True)
    np.testing.assert_array_equal(speech.pcm, np.concatenate(chunks))
    assert speech.available_frames() == 11
    with pytest.raises(ValueError, match="sequence"):
        speech.append(chunks[0], 1, True)


@pytest.mark.asyncio
async def test_stream_start_uses_two_frames_then_reuses_the_prediction_carry():
    class Renderer:
        def render_batch(self, avatar, mel, start, frame_start, count, carry, *, mel_origin):
            calls.append((start, count, id(carry)))
            return [np.zeros((2, 2, 3), dtype=np.uint8)] * count, 0.001

    calls = []
    session = RenderSession(Renderer(), SimpleNamespace(frame=lambda index: np.zeros((2, 2, 3), dtype=np.uint8)),
                            asyncio.Lock(), 8)
    session.upload(1, np.ones(640 * 20, dtype=np.int16), 0, True)
    session.start()
    try:
        for _ in range(32):
            await asyncio.wait_for(session.video.get(), 5)
            await asyncio.wait_for(session.audio.get(), 5)
        assert calls[:3] == [(0, 2, calls[0][2]), (2, 8, calls[0][2]), (10, 8, calls[0][2])]
    finally:
        await session.close()


def test_late_cancel_keeps_the_newer_generation_queued():
    session = RenderSession(SimpleNamespace(), SimpleNamespace(), asyncio.Lock(), 8)
    session.upload(1, np.ones(100, dtype=np.int16), 0, False)
    session.upload(2, np.ones(100, dtype=np.int16), 0, False)
    session.interrupt(1)
    session.upload(2, np.ones(100, dtype=np.int16), 1, True)
    assert [speech.source_generation for speech in session.utterances] == [2]
    assert session.speech_status(1)["state"] == "cancelled"
    assert session.speech_status(2)["state"] == "buffering"
    assert len(session.speeches[2].pcm) == 200


@pytest.mark.asyncio
async def test_a_chunk_arriving_within_playout_reserve_does_not_insert_silence():
    class Renderer:
        def render_batch(self, avatar, mel, start, frame_start, count, carry, *, mel_origin):
            return [np.zeros((2, 2, 3), dtype=np.uint8)] * count, .001

    session = RenderSession(Renderer(), SimpleNamespace(frame=lambda index: np.zeros((2, 2, 3), dtype=np.uint8)),
                            asyncio.Lock(), 8)
    session.upload(1, np.ones(5123, dtype=np.int16), 0, False)
    speech = session.speeches[1]
    speech.offset = 2
    session.clock = __import__("time").monotonic() + .2
    session.start()
    try:
        await asyncio.sleep(.03)
        session.upload(1, np.ones(5120, dtype=np.int16), 1, True)
        frame = await asyncio.wait_for(session.audio.get(), 3)
        assert frame[3][0] is speech
        assert speech.underruns == 0
    finally:
        await session.close()


def test_cancel_reclaims_unplayed_slots_and_owned_lead_in():
    session = RenderSession(SimpleNamespace(), SimpleNamespace(), asyncio.Lock(), 8)
    session.upload(1, np.ones(8000, dtype=np.int16), 0, True)
    speech = session.speeches[1]
    session.current_speech = speech
    session.presented_index = 4
    session.index = 20
    session.video.put_nowait((19, 0, None, (speech, False, True)))
    session.audio.put_nowait((19, 0, None, (speech, False, True)))
    session.interrupt(1)
    assert session.index == 5
    assert session.generation == 1
    assert session.video.empty() and session.audio.empty()


def test_late_cancel_does_not_retime_a_newer_frame_already_waiting_for_playout():
    session = RenderSession(SimpleNamespace(), SimpleNamespace(), asyncio.Lock(), 8)
    session.upload(2, np.ones(8000, dtype=np.int16), 0, True)
    speech = session.speeches[2]
    session.index = 20
    session.waiting["audio"] = (19, 0, None, (speech, False, False))
    session.interrupt(1)
    assert session.index == 20
    assert session.generation == 0
    assert not speech.cancelled
