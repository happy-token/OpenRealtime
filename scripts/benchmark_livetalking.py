"""Run a reproducible LiveTalking WebRTC stability and interruption benchmark."""

from __future__ import annotations

import argparse
import asyncio
import bisect
import hashlib
import json
import math
import os
import re
import shutil
import socket
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIO_SOURCE_BYTES = 32 * 1024 * 1024
UTC_TZ = timezone.utc  # noqa: UP017 -- runtime is pinned to Python 3.10.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.avatar_evaluation import BenchmarkRecord, append_benchmark_record
from scripts.livetalking_provider import (
    LiveTalkingRuntime,
    build_livetalking_server_command,
    build_livetalking_server_environment,
    inspect_livetalking_runtime,
)


@dataclass(frozen=True)
class RepeatedWav:
    path: Path
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    size_bytes: int


@dataclass(frozen=True)
class StreamObservation:
    connected_ms: float
    video_arrival_ms: tuple[float, ...]
    video_media_ms: tuple[float, ...]
    audio_arrival_ms: tuple[float, ...]
    audio_media_ms: tuple[float, ...]
    speaking_start_ms: float
    speaking_end_ms: float
    interrupt_latencies_ms: tuple[float, ...]


@dataclass(frozen=True)
class StabilityMetrics:
    stable_minutes: float
    average_fps: float
    second_half_fps: float
    first_frame_ms: float
    av_drift_ms: float
    queue_growth_frames: float
    interrupt_p95_ms: float
    video_frame_count: int
    audio_frame_count: int


LIVETALKING_METRIC_KINDS = {
    "first_frame_ms": "webrtc_idle_connection_frame",
    "av_drift_ms": "rtp_media_clock_p99",
    "queue_growth_frames": "receiver_frame_deficit",
    "interrupt_p95_ms": "server_output_state",
}


def build_canonical_benchmark_record(
    *,
    run_id: str,
    recorded_at: str,
    duration_seconds: float,
    observation: StreamObservation,
    metrics: StabilityMetrics,
    evidence_relative_path: str,
) -> BenchmarkRecord:
    """Keep non-acceptance observations out of generic realtime verdict fields."""

    return BenchmarkRecord(
        run_id=run_id,
        provider="livetalking-wav2lip96",
        artifact_id="livetalking-wav2lip96-001",
        mode="realtime",
        status="experimental",
        recorded_at=recorded_at,
        duration_seconds=duration_seconds,
        render_seconds=(observation.speaking_end_ms - observation.speaking_start_ms) / 1000,
        performance_metric_kind="paced_playback",
        average_fps=metrics.average_fps,
        first_frame_ms=None,
        av_drift_ms=None,
        stable_minutes=metrics.stable_minutes,
        queue_growth=None,
        interrupt_p95_ms=None,
        second_half_fps=metrics.second_half_fps,
        thermal_state="unknown",
        notes=(
            "Apple M1 MPS 10-minute local WebRTC stability run; "
            f"idle_webrtc_first_frame_ms={metrics.first_frame_ms:.3f}; "
            f"rtp_media_clock_drift_p99_ms={metrics.av_drift_ms:.3f}; "
            f"receiver_frame_deficit={metrics.queue_growth_frames:.3f}; "
            f"server_output_state_interrupt_p95_ms={metrics.interrupt_p95_ms:.3f}; "
            "generic acceptance fields are intentionally null because speaking first frame, "
            "image lip-sync, queue depth, and receiver-visible interruption were not measured; "
            f"evidence={evidence_relative_path}; "
            "standard Wav2Lip 96 is internal non-commercial evaluation only"
        ),
    )


def build_repeated_pcm_wav(
    source: Path,
    output: Path,
    *,
    duration_seconds: float,
) -> RepeatedWav:
    """Repeat a short PCM input into an exact, bounded local stability stimulus."""

    if not math.isfinite(duration_seconds) or duration_seconds <= 0 or duration_seconds > 600:
        raise ValueError("duration_seconds must be finite and no greater than 600 seconds")
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    try:
        with wave.open(str(source), "rb") as input_wav:
            channels = input_wav.getnchannels()
            sample_width = input_wav.getsampwidth()
            sample_rate = input_wav.getframerate()
            compression = input_wav.getcomptype()
            source_frames = input_wav.readframes(input_wav.getnframes())
    except (EOFError, wave.Error) as error:
        raise ValueError("stability source must be a valid WAV file") from error
    if (channels, sample_width, sample_rate, compression) != (1, 2, 16_000, "NONE"):
        raise ValueError("stability source must be PCM16 mono at 16kHz")
    bytes_per_frame = channels * sample_width
    if not source_frames or len(source_frames) % bytes_per_frame:
        raise ValueError("stability source contains no complete PCM frames")
    target_frames = round(duration_seconds * sample_rate)
    target_bytes = target_frames * bytes_per_frame
    repeats, remainder = divmod(target_bytes, len(source_frames))
    payload = source_frames * repeats + source_frames[:remainder]
    with wave.open(str(output), "wb") as generated:
        generated.setnchannels(channels)
        generated.setsampwidth(sample_width)
        generated.setframerate(sample_rate)
        generated.writeframes(payload)
    return RepeatedWav(
        path=output,
        duration_seconds=target_frames / sample_rate,
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        size_bytes=output.stat().st_size,
    )


def derive_stability_metrics(
    observation: StreamObservation,
    *,
    expected_duration_seconds: float,
) -> StabilityMetrics:
    """Validate complete WebRTC evidence and derive the canonical long-run metrics."""

    if not math.isfinite(expected_duration_seconds) or expected_duration_seconds < 600:
        raise ValueError("a 10-minute expected duration is required")
    sequences = (
        ("video", observation.video_arrival_ms, observation.video_media_ms),
        ("audio", observation.audio_arrival_ms, observation.audio_media_ms),
    )
    for label, arrivals, media_times in sequences:
        if len(arrivals) < 2 or len(arrivals) != len(media_times):
            raise ValueError(f"{label} timeline is incomplete")
        if any(not math.isfinite(value) or value < 0 for value in (*arrivals, *media_times)):
            raise ValueError(f"{label} timeline values must be finite and non-negative")
        if any(right <= left for left, right in pairwise(arrivals)):
            raise ValueError(f"{label} arrival timeline must be strictly monotonic")
        if any(right < left for left, right in pairwise(media_times)):
            raise ValueError(f"{label} media timeline must be monotonic")
    if (
        not math.isfinite(observation.speaking_start_ms)
        or not math.isfinite(observation.speaking_end_ms)
        or observation.speaking_start_ms < 0
        or observation.speaking_end_ms <= observation.speaking_start_ms
    ):
        raise ValueError("speaking interval is invalid")
    speaking_duration_ms = observation.speaking_end_ms - observation.speaking_start_ms
    if speaking_duration_ms < expected_duration_seconds * 1000 - 1_000:
        raise ValueError("speaking interval did not cover the 10-minute stimulus")
    if len(observation.interrupt_latencies_ms) < 5 or any(
        not math.isfinite(value) or value < 0 for value in observation.interrupt_latencies_ms
    ):
        raise ValueError("at least five finite interrupt latency trials are required")

    for label, arrivals, _ in sequences:
        speaking_arrivals = tuple(
            value
            for value in arrivals
            if observation.speaking_start_ms <= value <= observation.speaking_end_ms
        )
        if (
            len(speaking_arrivals) < 2
            or speaking_arrivals[0] - observation.speaking_start_ms > 500
            or observation.speaking_end_ms - speaking_arrivals[-1] > 500
        ):
            raise ValueError(f"{label} timeline does not cover the stability window endpoints")
        if max(right - left for left, right in pairwise(speaking_arrivals)) > 250:
            raise ValueError(f"{label} timeline contains a stability gap greater than 250ms")

    video_indices = tuple(
        index
        for index, arrival in enumerate(observation.video_arrival_ms)
        if observation.speaking_start_ms <= arrival <= observation.speaking_end_ms
    )
    if len(video_indices) < expected_duration_seconds * 20:
        raise ValueError("video timeline does not cover the 10-minute speaking interval")
    speaking_video_arrivals = tuple(observation.video_arrival_ms[index] for index in video_indices)
    average_fps = _fps(speaking_video_arrivals)
    midpoint = observation.speaking_start_ms + speaking_duration_ms / 2
    second_half = tuple(value for value in speaking_video_arrivals if value >= midpoint)
    if len(second_half) < 2:
        raise ValueError("second-half video timeline is incomplete")

    first_frame_ms = observation.video_arrival_ms[0] - observation.connected_ms
    if not math.isfinite(first_frame_ms) or first_frame_ms < 0:
        raise ValueError("first video frame precedes the WebRTC connection")
    av_drift_ms = _p99_av_clock_drift_ms(
        observation,
        start_ms=observation.speaking_start_ms,
        end_ms=observation.speaking_end_ms,
    )
    expected_video_frames = round(speaking_duration_ms / 1000 * 25)
    queue_growth_frames = float(max(0, expected_video_frames - len(video_indices)))
    interrupt_p95_ms = _nearest_rank_percentile(observation.interrupt_latencies_ms, 0.95)
    return StabilityMetrics(
        stable_minutes=speaking_duration_ms / 60_000,
        average_fps=average_fps,
        second_half_fps=_fps(second_half),
        first_frame_ms=first_frame_ms,
        av_drift_ms=av_drift_ms,
        queue_growth_frames=queue_growth_frames,
        interrupt_p95_ms=interrupt_p95_ms,
        video_frame_count=len(observation.video_arrival_ms),
        audio_frame_count=len(observation.audio_arrival_ms),
    )


def _fps(timestamps_ms: tuple[float, ...]) -> float:
    return (len(timestamps_ms) - 1) * 1000 / (timestamps_ms[-1] - timestamps_ms[0])


def _p99_av_clock_drift_ms(
    observation: StreamObservation,
    *,
    start_ms: float,
    end_ms: float,
) -> float:
    offsets: list[float] = []
    audio_arrivals = observation.audio_arrival_ms
    for video_arrival, video_media in zip(
        observation.video_arrival_ms, observation.video_media_ms, strict=True
    ):
        if not start_ms <= video_arrival <= end_ms:
            continue
        insertion = bisect.bisect_left(audio_arrivals, video_arrival)
        candidates = [
            index for index in (insertion - 1, insertion) if 0 <= index < len(audio_arrivals)
        ]
        nearest = min(candidates, key=lambda index: abs(audio_arrivals[index] - video_arrival))
        if abs(audio_arrivals[nearest] - video_arrival) <= 100:
            offsets.append(video_media - observation.audio_media_ms[nearest])
    if len(offsets) < 25:
        raise ValueError("audio/video timelines do not overlap sufficiently")
    baseline = statistics.median(offsets[:25])
    deviations = tuple(abs(offset - baseline) for offset in offsets)
    return _nearest_rank_percentile(deviations, 0.99)


def _nearest_rank_percentile(values: tuple[float, ...], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _validate_run_id(run_id: str) -> None:
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?", run_id) is None:
        raise ValueError("run_id must be a lowercase canonical identifier")


def _validate_audio_source(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("benchmark audio must be a readable regular file") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError("benchmark audio must be a regular non-symbolic-link file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_AUDIO_SOURCE_BYTES:
        raise ValueError("benchmark audio must be between 1 byte and 32 MiB")
    return path.resolve()


def _require_port_available(port: int) -> None:
    """Fail before model launch if the benchmark port already has a listener."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as error:
        raise RuntimeError(f"benchmark port {port} is already in use") from error
    finally:
        probe.close()


async def _wait_for_port(
    process: subprocess.Popen[bytes], port: int, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"LiveTalking server exited with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            await asyncio.sleep(0.25)
    raise TimeoutError("LiveTalking server did not become ready")


async def _poll_speaking(session, base_url: str, session_id: str, expected: bool, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with session.post(
            f"{base_url}/is_speaking", json={"sessionid": session_id}
        ) as response:
            payload = await response.json()
        if response.status == 200 and payload.get("code") == 0 and payload.get("data") is expected:
            return _now_ms()
        await asyncio.sleep(0.02 if not expected else 0.05)
    raise TimeoutError(f"LiveTalking speaking state did not become {expected}")


async def _upload_audio(session, base_url: str, session_id: str, path: Path) -> None:
    import aiohttp

    form = aiohttp.FormData()
    form.add_field("sessionid", session_id)
    form.add_field("file", path.read_bytes(), filename=path.name, content_type="audio/wav")
    async with session.post(f"{base_url}/humanaudio", data=form) as response:
        payload = await response.json()
    if response.status != 200 or payload.get("code") != 0:
        raise RuntimeError(f"LiveTalking audio upload failed: {payload}")


async def collect_livetalking_observation(
    *,
    base_url: str,
    short_audio: Path,
    stability_audio: Path,
    stability_duration_seconds: float,
    interrupt_trials: int,
) -> StreamObservation:
    """Negotiate WebRTC, exercise interruptions, then observe a continuous long stimulus."""

    import aiohttp
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.mediastreams import MediaStreamError

    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    video_arrivals: list[float] = []
    video_media: list[float] = []
    audio_arrivals: list[float] = []
    audio_media: list[float] = []
    consumers: list[asyncio.Task[None]] = []
    connected_event = asyncio.Event()
    first_video_event = asyncio.Event()
    connected_ms: float | None = None

    async def consume(track) -> None:
        arrivals = video_arrivals if track.kind == "video" else audio_arrivals
        media_times = video_media if track.kind == "video" else audio_media
        try:
            while True:
                frame = await track.recv()
                if frame.pts is None or frame.time_base is None:
                    continue
                arrivals.append(_now_ms())
                media_times.append(float(frame.pts * frame.time_base * 1000))
                if track.kind == "video":
                    first_video_event.set()
        except MediaStreamError:
            return

    @pc.on("track")
    def on_track(track) -> None:
        consumers.append(asyncio.create_task(consume(track)))

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        nonlocal connected_ms
        if pc.connectionState == "connected" and connected_ms is None:
            connected_ms = _now_ms()
            connected_event.set()

    headers = {"Origin": "http://127.0.0.1:3010"}
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_connect=30, sock_read=30)
    interrupt_latencies: list[float] = []
    speaking_start_ms: float | None = None
    speaking_end_ms: float | None = None
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            async with session.post(
                f"{base_url}/offer",
                json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            ) as response:
                answer = await response.json()
                response_status = response.status
            if response_status != 200 or not answer.get("sdp") or not answer.get("sessionid"):
                raise RuntimeError(f"LiveTalking WebRTC offer failed: {answer}")
            session_id = str(answer["sessionid"])
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
            )
            await asyncio.wait_for(connected_event.wait(), timeout=30)
            await asyncio.wait_for(first_video_event.wait(), timeout=30)

            for _ in range(interrupt_trials):
                await _upload_audio(session, base_url, session_id, short_audio)
                await _poll_speaking(session, base_url, session_id, True, 30)
                await asyncio.sleep(0.3)
                interrupt_started = _now_ms()
                async with session.post(
                    f"{base_url}/interrupt_talk", json={"sessionid": session_id}
                ) as response:
                    payload = await response.json()
                    response_status = response.status
                if response_status != 200 or payload.get("code") != 0:
                    raise RuntimeError(f"LiveTalking interrupt failed: {payload}")
                stopped_ms = await _poll_speaking(session, base_url, session_id, False, 30)
                interrupt_latencies.append(stopped_ms - interrupt_started)
                await asyncio.sleep(0.3)

            await _upload_audio(session, base_url, session_id, stability_audio)
            speaking_start_ms = await _poll_speaking(session, base_url, session_id, True, 30)
            minimum_end = time.monotonic() + stability_duration_seconds - 1
            while time.monotonic() < minimum_end:
                await asyncio.sleep(min(0.5, minimum_end - time.monotonic()))
                async with session.post(
                    f"{base_url}/is_speaking", json={"sessionid": session_id}
                ) as response:
                    payload = await response.json()
                    response_status = response.status
                if (
                    response_status != 200
                    or payload.get("code") != 0
                    or payload.get("data") is not True
                ):
                    raise RuntimeError(
                        "LiveTalking stopped speaking before the stability interval completed"
                    )
            speaking_end_ms = await _poll_speaking(session, base_url, session_id, False, timeout=30)
    finally:
        await pc.close()
        await asyncio.gather(*consumers, return_exceptions=True)

    assert connected_ms is not None
    assert speaking_start_ms is not None
    assert speaking_end_ms is not None
    return StreamObservation(
        connected_ms=connected_ms,
        video_arrival_ms=tuple(video_arrivals),
        video_media_ms=tuple(video_media),
        audio_arrival_ms=tuple(audio_arrivals),
        audio_media_ms=tuple(audio_media),
        speaking_start_ms=speaking_start_ms,
        speaking_end_ms=speaking_end_ms,
        interrupt_latencies_ms=tuple(interrupt_latencies),
    )


def run_livetalking_benchmark(
    *,
    runtime_root: Path,
    campaign: Path,
    audio_path: Path,
    run_id: str,
    duration_seconds: float,
    interrupt_trials: int,
    port: int,
    rights_confirmed: bool,
) -> dict[str, object]:
    """Launch the pinned local service, collect long-run evidence, and register it."""

    if rights_confirmed is not True:
        raise ValueError("Audio and avatar evaluation rights must be confirmed")
    if not math.isfinite(duration_seconds) or duration_seconds != 600:
        raise ValueError("the canonical stability benchmark must run for exactly 600 seconds")
    if interrupt_trials < 5 or interrupt_trials > 20:
        raise ValueError("interrupt_trials must be between 5 and 20")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    _validate_run_id(run_id)
    campaign = campaign.resolve()
    audio_path = _validate_audio_source(audio_path)
    if not audio_path.is_relative_to(campaign):
        raise ValueError("benchmark audio must stay inside the campaign directory")
    runtime = LiveTalkingRuntime(
        runtime_root.resolve() / "repository",
        runtime_root.resolve() / ".venv/bin/python",
    )
    diagnostic = inspect_livetalking_runtime(runtime, avatar_id="shuchang")
    if not diagnostic.ready:
        raise RuntimeError("LiveTalking runtime is not ready: " + "; ".join(diagnostic.issues))
    evidence_path = campaign / "runs/livetalking" / f"{run_id}.evidence.json"
    if evidence_path.exists():
        raise FileExistsError(evidence_path)
    benchmark_path = campaign / "benchmark.csv"
    if not benchmark_path.is_file():
        raise FileNotFoundError(benchmark_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".livetalking-stability-", dir=evidence_path.parent
    ) as name:
        temporary = Path(name)
        audio_snapshot = temporary / "source.wav"
        with audio_path.open("rb") as source, audio_snapshot.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        stability_audio = temporary / "stability.wav"
        repeated = build_repeated_pcm_wav(
            audio_snapshot, stability_audio, duration_seconds=duration_seconds
        )
        server_log = temporary / "server.log"
        command = build_livetalking_server_command(
            runtime,
            avatar_id="shuchang",
            port=port,
            batch_size=4,
        )
        environment = build_livetalking_server_environment()
        environment["LIVETALKING_ENABLE_EVALUATION_ROUTES"] = "0"
        _require_port_available(port)
        with server_log.open("wb") as log_output:
            process = subprocess.Popen(
                command,
                cwd=runtime.repository,
                env=environment,
                stdout=log_output,
                stderr=subprocess.STDOUT,
            )
            try:
                asyncio.run(_wait_for_port(process, port, 180))
                observation = asyncio.run(
                    asyncio.wait_for(
                        collect_livetalking_observation(
                            base_url=f"http://127.0.0.1:{port}",
                            short_audio=audio_snapshot,
                            stability_audio=stability_audio,
                            stability_duration_seconds=duration_seconds,
                            interrupt_trials=interrupt_trials,
                        ),
                        timeout=duration_seconds + 180,
                    )
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        metrics = derive_stability_metrics(observation, expected_duration_seconds=duration_seconds)
        log_tail = server_log.read_text(encoding="utf-8", errors="replace")[-20_000:]
        recorded_at = datetime.now(UTC_TZ).isoformat()
        payload = {
            "schema_version": 2,
            "run_id": run_id,
            "provider": "livetalking-wav2lip96",
            "recorded_at": recorded_at,
            "runtime_commit": diagnostic.ready and "36837f90f8db3f59e1d7fcdd111a7db3842515d0",
            "avatar_id": "shuchang",
            "input": {
                "path": audio_path.relative_to(campaign).as_posix(),
                "sha256": _sha256(audio_snapshot),
                "stability_duration_seconds": repeated.duration_seconds,
                "stability_size_bytes": repeated.size_bytes,
                "sample_rate_hz": repeated.sample_rate_hz,
                "channels": repeated.channels,
            },
            "observation": asdict(observation),
            "metrics": asdict(metrics),
            "metric_kinds": LIVETALKING_METRIC_KINDS,
            "server_log_tail": log_tail,
            "limitations": [
                "First frame is the initial idle WebRTC frame after connection, not the first audio-driven speaking frame.",
                "AV drift is P99 RTP audio/video media-clock drift during the stability window, not image-based lip-sync error.",
                "queue_growth is a receiver-frame deficit, not sampled server or WebRTC queue depth.",
                "Interrupt latency ends when the server output state becomes idle, not when the receiver stops presenting old media.",
                "Standard Wav2Lip 96 remains restricted to internal non-commercial evaluation.",
            ],
        }
        staged_evidence = temporary / "evidence.json"
        with staged_evidence.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(staged_evidence, evidence_path)
        try:
            append_benchmark_record(
                benchmark_path,
                build_canonical_benchmark_record(
                    run_id=run_id,
                    recorded_at=recorded_at,
                    duration_seconds=duration_seconds,
                    observation=observation,
                    metrics=metrics,
                    evidence_relative_path=evidence_path.relative_to(campaign).as_posix(),
                ),
            )
        except BaseException:
            evidence_path.unlink(missing_ok=True)
            raise
        return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path("models/livetalking"))
    parser.add_argument(
        "--campaign",
        type=Path,
        default=Path("research-assets/avatar-evaluation/2026-08-22"),
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=Path("research-assets/avatar-evaluation/2026-08-22/inputs/wav2lip-speech-3s.wav"),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument("--interrupt-trials", type=int, default=5)
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--rights-confirmed", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    payload = run_livetalking_benchmark(
        runtime_root=args.runtime_root,
        campaign=args.campaign,
        audio_path=args.audio,
        run_id=args.run_id,
        duration_seconds=args.duration_seconds,
        interrupt_trials=args.interrupt_trials,
        port=args.port,
        rights_confirmed=args.rights_confirmed,
    )
    print(
        json.dumps(
            {
                "run_id": payload["run_id"],
                "provider": payload["provider"],
                "metrics": payload["metrics"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
