import json
import wave
from pathlib import Path

import pytest

from scripts import benchmark_dh_live
from scripts.benchmark_dh_live import (
    BenchmarkWav,
    BrowserBenchmarkEvidence,
    NormalizedVideo,
    build_browser_worker_command,
    build_dh_live_normalize_command,
    load_browser_benchmark_evidence,
    probe_benchmark_wav,
    probe_normalized_video,
    publish_benchmark_files,
    publish_file_no_replace,
    run_dh_live_benchmark,
    snapshot_bounded_regular_file,
    validate_browser_benchmark_evidence,
)
from scripts.dh_live_provider import DHLiveDiagnostic


def valid_evidence() -> BrowserBenchmarkEvidence:
    return BrowserBenchmarkEvidence(
        canvas_width=720,
        canvas_height=1080,
        speech_audio_bytes=99_918,
        control_audio_bytes=99_918,
        set_audio_buffer_calls=2,
        control_timestamps_ms=tuple(float(value) for value in range(0, 1001, 40)),
        control_blend_shape_deltas=(0.0,) + (0.5,) * 25,
        speech_timestamps_ms=tuple(float(value) for value in range(0, 1001, 40)),
        speech_blend_shape_deltas=(0.0, 0.6, 0.8, 1.7) + (4.0,) * 22,
        browser_version="HeadlessChrome/140.0.0.0",
        webgl_version="WebGL 2.0",
    )


def test_validate_browser_evidence_requires_real_audio_driven_rendering() -> None:
    evidence = valid_evidence()

    metrics = validate_browser_benchmark_evidence(
        evidence, expected_audio_bytes=99_918, expected_duration_seconds=1.0
    )

    assert metrics.renderer_update_samples == 26
    assert metrics.average_fps == pytest.approx(25.0)
    assert metrics.second_half_fps == pytest.approx(25.0)
    assert metrics.first_audio_driven_blend_change_ms == 120.0
    assert metrics.silence_calibrated_threshold == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"set_audio_buffer_calls": 1}, "audio buffers"),
        ({"speech_audio_bytes": 99_917}, "audio byte count"),
        (
            {
                "speech_timestamps_ms": (0.0, 40.0, 39.0)
                + tuple(float(value) for value in range(120, 1001, 40))
            },
            "monotonic",
        ),
        ({"speech_blend_shape_deltas": (0.0,) + (0.5,) * 25}, "silence baseline"),
        (
            {"speech_timestamps_ms": tuple(float(value) for value in range(0, 501, 20))},
            "full audio duration",
        ),
        (
            {
                "speech_timestamps_ms": (-1.0,)
                + tuple(float(value) for value in range(40, 1001, 40))
            },
            "non-negative",
        ),
        (
            {"speech_timestamps_ms": tuple(float(value) for value in range(0, 1151, 46))},
            "exceed the audio duration",
        ),
        (
            {"control_blend_shape_deltas": (-0.1,) + (0.5,) * 25},
            "non-negative",
        ),
        ({"webgl_version": "WebGL 1.0"}, "WebGL2"),
    ],
)
def test_validate_browser_evidence_rejects_false_positive_runs(
    changes: dict[str, object],
    message: str,
) -> None:
    values = valid_evidence().__dict__ | changes

    with pytest.raises(ValueError, match=message):
        validate_browser_benchmark_evidence(
            BrowserBenchmarkEvidence(**values), 99_918, expected_duration_seconds=1.0
        )


def test_build_normalize_command_muxes_the_exact_audio_without_shell() -> None:
    command = build_dh_live_normalize_command(
        raw_video=Path("raw capture.webm"),
        audio=Path("input voice.wav"),
        output=Path("result.mp4"),
        duration_seconds=3.12,
        ffmpeg_bin="/opt/ffmpeg",
    )

    assert command == [
        "/opt/ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        "raw capture.webm",
        "-i",
        "input voice.wav",
        "-t",
        "3.120",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        "fps=25,scale=720:1080:flags=lanczos,pad=720:1280:0:100:black,tpad=stop_mode=clone:stop_duration=0.200,format=yuv420p",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "24000",
        "-ac",
        "1",
        "result.mp4",
    ]


def test_load_browser_evidence_accepts_only_the_expected_schema(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    payload = {
        "canvas_width": 720,
        "canvas_height": 1080,
        "speech_audio_bytes": 99_918,
        "control_audio_bytes": 99_918,
        "set_audio_buffer_calls": 2,
        "control_timestamps_ms": [0.0, 40.0, 80.0],
        "control_blend_shape_deltas": [0.0, 0.1, 0.2],
        "speech_timestamps_ms": [0.0, 40.0, 80.0],
        "speech_blend_shape_deltas": [0.0, 1.0, 2.0],
        "browser_version": "HeadlessChrome/140.0.0.0",
        "webgl_version": "WebGL 2.0",
    }
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence = load_browser_benchmark_evidence(evidence_path)

    assert evidence.speech_timestamps_ms == (0.0, 40.0, 80.0)
    payload["set_audio_buffer_calls"] = True
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="set_audio_buffer_calls"):
        load_browser_benchmark_evidence(evidence_path)


def test_load_browser_evidence_rejects_invalid_json_and_unknown_fields(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid browser benchmark evidence"):
        load_browser_benchmark_evidence(evidence_path)

    evidence_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected schema"):
        load_browser_benchmark_evidence(evidence_path)


def test_probe_benchmark_wav_requires_pcm16_mono_16khz(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)

    wav = probe_benchmark_wav(audio_path)

    assert wav.duration_seconds == 1.0
    assert wav.size_bytes == audio_path.stat().st_size

    stereo_path = tmp_path / "stereo.wav"
    with wave.open(str(stereo_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0\0\0")
    with pytest.raises(ValueError, match="PCM16 mono"):
        probe_benchmark_wav(stereo_path)

    with pytest.raises(FileNotFoundError):
        probe_benchmark_wav(tmp_path / "missing.wav")

    valid_bytes = audio_path.read_bytes()
    truncated_path = tmp_path / "truncated.wav"
    truncated_path.write_bytes(valid_bytes[:44])
    with pytest.raises(ValueError, match="truncated PCM"):
        probe_benchmark_wav(truncated_path)


def test_audio_snapshot_rejects_symlink_and_oversized_input(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    alias = tmp_path / "alias.wav"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="regular file"):
        snapshot_bounded_regular_file(alias, tmp_path / "alias-copy.wav", max_bytes=10)

    oversized = tmp_path / "oversized.wav"
    oversized.write_bytes(b"x" * 11)
    with pytest.raises(ValueError, match="size boundary"):
        snapshot_bounded_regular_file(oversized, tmp_path / "large-copy.wav", max_bytes=10)


def test_build_browser_worker_command_is_explicit_and_bounded() -> None:
    command = build_browser_worker_command(
        node_bin="/opt/node",
        worker=Path("scripts/dh live worker.mjs"),
        renderer_url="http://127.0.0.1:8891/MiniLive.html",
        audio=Path("input.wav"),
        control_audio=Path("silence.wav"),
        raw_video=Path("capture.webm"),
        evidence=Path("evidence.json"),
        duration_seconds=3.12,
    )

    assert command == [
        "/opt/node",
        "scripts/dh live worker.mjs",
        "--renderer-url",
        "http://127.0.0.1:8891/MiniLive.html",
        "--audio",
        "input.wav",
        "--control-audio",
        "silence.wav",
        "--raw-video",
        "capture.webm",
        "--evidence",
        "evidence.json",
        "--duration-ms",
        "3120",
        "--canvas-width",
        "720",
        "--canvas-height",
        "1080",
    ]

    with pytest.raises(ValueError, match="60 seconds"):
        build_browser_worker_command(
            node_bin="node",
            worker=Path("worker.mjs"),
            renderer_url="http://127.0.0.1:8891/MiniLive.html",
            audio=Path("input.wav"),
            control_audio=Path("silence.wav"),
            raw_video=Path("capture.webm"),
            evidence=Path("evidence.json"),
            duration_seconds=60.001,
        )
    with pytest.raises(ValueError, match="loopback"):
        build_browser_worker_command(
            node_bin="node",
            worker=Path("worker.mjs"),
            renderer_url="https://example.com/MiniLive.html",
            audio=Path("input.wav"),
            control_audio=Path("silence.wav"),
            raw_video=Path("capture.webm"),
            evidence=Path("evidence.json"),
            duration_seconds=1,
        )


def test_run_rejects_unsafe_identity_before_starting_external_tools(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    output = campaign / "runs" / "dh-live-mini" / "unsafe.mp4"

    with pytest.raises(ValueError, match="run_id"):
        run_dh_live_benchmark(
            runtime_root=tmp_path / "runtime",
            campaign=campaign,
            audio_path=tmp_path / "missing.wav",
            output_path=output,
            run_id="../unsafe",
            rights_confirmed=True,
        )

    with pytest.raises(ValueError, match="rights"):
        run_dh_live_benchmark(
            runtime_root=tmp_path / "runtime",
            campaign=campaign,
            audio_path=tmp_path / "missing.wav",
            output_path=output,
            run_id="unsafe",
            rights_confirmed=False,
        )


def test_probe_normalized_video_parses_and_enforces_media_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 720,
                "height": 1280,
                "r_frame_rate": "25/1",
                "nb_read_frames": "78",
                "duration": "3.120",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "24000",
                "duration": "3.120",
                "channels": 1,
            },
        ],
        "format": {"duration": "3.120", "size": "259926"},
    }
    monkeypatch.setattr(
        benchmark_dh_live,
        "_run",
        lambda *args, **kwargs: benchmark_dh_live.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    video = probe_normalized_video(
        tmp_path / "artifact.mp4", ffprobe_bin="ffprobe", expected_duration_seconds=3.12
    )

    assert video == NormalizedVideo(
        3.12, 259_926, "h264", "aac", 720, 1280, 25.0, 78, 24_000, 3.12, 3.12, 1
    )
    payload["streams"][0]["codec_name"] = "vp9"
    with pytest.raises(ValueError, match="media contract"):
        probe_normalized_video(tmp_path / "artifact.mp4", ffprobe_bin="ffprobe")


def test_run_benchmark_persists_evidence_artifact_and_canonical_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "benchmark.csv").write_text("header\n", encoding="utf-8")
    audio = campaign / "inputs" / "speech.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"benchmark-audio")
    output = campaign / "runs" / "dh-live-mini" / "dh-live-mini-browser-test.mp4"
    records = []

    class FakeServer:
        server_port = 45123

        def serve_forever(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

        def server_close(self) -> None:
            return None

    evidence_payload = {
        "canvas_width": 720,
        "canvas_height": 1080,
        "speech_audio_bytes": len(b"benchmark-audio"),
        "control_audio_bytes": len(b"benchmark-audio"),
        "set_audio_buffer_calls": 2,
        "control_timestamps_ms": [0.0, 40.0, 80.0, 120.0],
        "control_blend_shape_deltas": [0.0, 0.1, 0.2, 0.1],
        "speech_timestamps_ms": [0.0, 40.0, 80.0, 120.0],
        "speech_blend_shape_deltas": [0.7, 0.8, 1.2, 2.0],
        "browser_version": "HeadlessChrome/151",
        "webgl_version": "WebGL 2.0",
    }

    def fake_run(command: list[str], **kwargs: object):
        if "--evidence" in command:
            evidence = Path(command[command.index("--evidence") + 1])
            raw_video = Path(command[command.index("--raw-video") + 1])
            evidence.write_text(json.dumps(evidence_payload), encoding="utf-8")
            raw_video.write_bytes(b"webm")
        elif command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"normalized-mp4")
        return benchmark_dh_live.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        benchmark_dh_live,
        "probe_benchmark_wav",
        lambda path: BenchmarkWav(path, len(b"benchmark-audio"), 0.12, 16_000, 1, 2),
    )
    monkeypatch.setattr(
        benchmark_dh_live,
        "inspect_dh_live_runtime",
        lambda runtime: DHLiveDiagnostic(
            ready=True,
            device="browser-cpu-webgl",
            sample_frames=179,
            license_status="review",
            issues=(),
        ),
    )
    monkeypatch.setattr(benchmark_dh_live, "_required_executable", lambda name: name)
    monkeypatch.setattr(
        benchmark_dh_live,
        "create_dh_live_server",
        lambda *args, **kwargs: FakeServer(),
    )
    monkeypatch.setattr(benchmark_dh_live, "_run", fake_run)
    monkeypatch.setattr(
        benchmark_dh_live,
        "probe_normalized_video",
        lambda path, ffprobe_bin, expected_duration_seconds: NormalizedVideo(
            0.12, path.stat().st_size, "h264", "aac", 720, 1280, 25.0, 3, 24_000, 0.12, 0.12, 1
        ),
    )
    monkeypatch.setattr(
        benchmark_dh_live, "append_benchmark_record", lambda path, record: records.append(record)
    )

    result = run_dh_live_benchmark(
        runtime_root=tmp_path / "runtime",
        campaign=campaign,
        audio_path=audio,
        output_path=output,
        run_id="dh-live-mini-browser-test",
        rights_confirmed=True,
    )

    assert output.read_bytes() == b"normalized-mp4"
    assert output.with_suffix(".evidence.json").is_file()
    assert result["avatar_scope"] == "official-prebuilt-sample-not-campaign-portrait"
    assert records[0].provider == "dh-live-mini"
    assert records[0].average_fps == pytest.approx(25.0)
    assert records[0].first_frame_ms is None


def test_probe_wav_rejects_large_trailing_payload(tmp_path: Path) -> None:
    audio = tmp_path / "oversized.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)
    with audio.open("ab") as output:
        output.write(b"x" * 70_000)

    with pytest.raises(ValueError, match="unexpected trailing data"):
        probe_benchmark_wav(audio)


def test_publish_file_no_replace_never_overwrites_existing_file(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    destination = tmp_path / "destination"
    staged.write_bytes(b"new")
    destination.write_bytes(b"canary")

    with pytest.raises(FileExistsError):
        publish_file_no_replace(staged, destination)

    assert destination.read_bytes() == b"canary"
    assert staged.read_bytes() == b"new"


def test_publish_benchmark_files_rolls_back_if_record_append_fails(tmp_path: Path) -> None:
    staged_video = tmp_path / "staged.mp4"
    staged_evidence = tmp_path / "staged.json"
    output = tmp_path / "final.mp4"
    evidence = tmp_path / "final.json"
    staged_video.write_bytes(b"video")
    staged_evidence.write_bytes(b"evidence")

    def fail_append() -> None:
        raise RuntimeError("append failed")

    with pytest.raises(RuntimeError, match="append failed"):
        publish_benchmark_files(
            staged_video=staged_video,
            staged_evidence=staged_evidence,
            output_path=output,
            evidence_path=evidence,
            append_record=fail_append,
        )

    assert not output.exists()
    assert not evidence.exists()
