"""OpenRealtime WebRTC renderer; compatible with the existing browser audio bridge.

No upstream LiveTalking application is imported or launched. Audio and video
are emitted from the same bounded frame queue and share one presentation clock.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import math
import os
import tempfile
import time
import uuid
import wave
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from aiohttp import web
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
)

from server.avatar_compositing import CompositionConfig
from server.avatar_compositing.preparation import asset_path, is_prepared, prepare
from server.avatar_compositing.runtime import (
    FPS,
    SAMPLE_RATE,
    SAMPLES_PER_FRAME,
    AvatarFrames,
    AvatarRenderer,
    mel_spectrogram,
    stream_mel,
)

logger = logging.getLogger(__name__)


def decode_wav(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError("Expected mono PCM16 WAV at 16000 Hz")
        if not 0 < source.getnframes() <= SAMPLE_RATE * 120:
            raise ValueError("Audio must be between 0 and 120 seconds")
        raw = source.readframes(source.getnframes())
        if len(raw) != source.getnframes() * 2:
            raise ValueError("Truncated WAV")
    return np.frombuffer(raw, dtype="<i2").copy()


class OutputTrack(MediaStreamTrack):
    def __init__(self, session: RenderSession, kind: str):
        super().__init__()
        self.session = session
        self.kind = kind

    async def recv(self):
        session = self.session
        queue = session.video if self.kind == "video" else session.audio
        while True:
            session.waiting.pop(self.kind, None)
            item = await queue.get()
            session.waiting[self.kind] = item
            index, generation, pixels = item[:3]
            if generation != session.generation:
                continue
            if session.clock is None:
                session.clock = time.monotonic() - index / FPS
            await asyncio.sleep(max(0, session.clock + index / FPS - time.monotonic()))
            if generation == session.generation and not (len(item) > 3 and item[3] and item[3][0].cancelled):
                break
        session.waiting.pop(self.kind, None)
        session.presented_index = max(session.presented_index, index)
        if self.kind == "video":
            frame = av.VideoFrame.from_ndarray(pixels, format="bgr24")
            frame.pts, frame.time_base = index * 3600, Fraction(1, 90000)
            session.delivered += 1
        else:
            frame = av.AudioFrame.from_ndarray(pixels.reshape(1, -1), format="s16", layout="mono")
            if len(item) > 3 and item[3] is not None and not item[3][2]:
                speech, last, _ = item[3]
                now = time.monotonic()
                speech.max_lateness_ms = max(speech.max_lateness_ms, (now - session.clock - index / FPS) * 1000)
                if speech.started_at is None:
                    speech.started_at = now
                if last:
                    speech.completed_at = now + 1 / FPS
            frame.sample_rate = SAMPLE_RATE
            frame.pts, frame.time_base = index * SAMPLES_PER_FRAME, Fraction(1, SAMPLE_RATE)
        return frame


@dataclass
class SpeechBuffer:
    source_generation: int
    pcm: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int16))
    sequence: int = 0
    final: bool = False
    offset: int = 0
    carry: dict[int, np.ndarray] = field(default_factory=dict)
    received_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    completed_at: float | None = None
    cancelled: bool = False
    underruns: int = 0
    max_lateness_ms: float = 0.0

    def append(self, pcm: np.ndarray, sequence: int, final: bool):
        if self.final or sequence != self.sequence:
            raise ValueError("Audio chunks must arrive once, in sequence, before final")
        if len(self.pcm) + len(pcm) > SAMPLE_RATE * 120:
            raise ValueError("A speech generation cannot exceed 120 seconds")
        self.pcm = np.concatenate((self.pcm, pcm))
        self.sequence += 1
        self.final = final

    def available_frames(self) -> int:
        if self.final:
            return math.ceil(len(self.pcm) / SAMPLES_PER_FRAME) - self.offset
        if self.offset == 0 and len(self.pcm) < SAMPLE_RATE * .48:
            return 0
        # The next even prediction needs 16 mel bins plus the STFT right wing.
        # Retain real future audio across HTTP chunks; pad only after final.
        available = (len(self.pcm) - 3600) // SAMPLES_PER_FRAME - self.offset
        return max(0, available // 2 * 2)


class RenderSession:
    def __init__(self, renderer: AvatarRenderer, avatar: AvatarFrames, lock: asyncio.Lock,
                 batch_size: int):
        self.renderer, self.avatar, self.lock = renderer, avatar, lock
        self.batch_size = batch_size
        # A full batch must fit while the next one computes. Four slots for
        # an eight-frame batch serialize compute and playout despite >25fps inference.
        self.video: asyncio.Queue = asyncio.Queue(maxsize=max(4, batch_size * 2))
        self.audio: asyncio.Queue = asyncio.Queue(maxsize=max(4, batch_size * 2))
        self.utterances: deque[SpeechBuffer] = deque()
        self.speeches: dict[int, SpeechBuffer] = {}
        self.clock: float | None = None
        self.generation = 0
        self.cancelled_through = -1
        self.index = 0
        self.presented_index = -1
        self.waiting: dict[str, tuple] = {}
        self.current_speech: SpeechBuffer | None = None
        self.delivered = 0
        self.timings: deque[float] = deque(maxlen=1000)
        self.rendered_frames = 0
        self.render_seconds = 0.0
        self.task: asyncio.Task | None = None
        self.failure: str | None = None
        self.speaking = False
        self.first_batches: deque[int] = deque(maxlen=16)
        self.input_changed = asyncio.Event()

    def upload(self, source_generation: int, pcm: np.ndarray, sequence: int, final: bool):
        if source_generation <= self.cancelled_through:
            return
        speech = self.speeches.get(source_generation)
        if speech is None:
            if len(self.utterances) >= 8:
                raise web.HTTPTooManyRequests(text="Audio queue full")
            if sequence != 0:
                raise ValueError("The first chunk must have sequence zero")
            speech = SpeechBuffer(source_generation)
            speech.append(pcm, sequence, final)
            self.speeches[source_generation] = speech
            self.utterances.append(speech)
            # Keep bounded status history, without evicting live generations.
            for key, old in list(self.speeches.items()):
                if len(self.speeches) <= 16:
                    break
                if old.completed_at is not None or old.cancelled:
                    del self.speeches[key]
        else:
            speech.append(pcm, sequence, final)
        self.input_changed.set()

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.produce())

    async def emit(self, image: np.ndarray, pcm: np.ndarray, generation: int,
                   speech: SpeechBuffer | None = None, last: bool = False, lead: bool = False):
        if generation != self.generation or (speech is not None and speech.cancelled):
            return
        marker = (speech, last, lead) if speech is not None else None
        await self.video.put((self.index, generation, image, marker))
        if generation != self.generation or (speech is not None and speech.cancelled):
            return
        await self.audio.put((self.index, generation, pcm, marker))
        if generation != self.generation or (speech is not None and speech.cancelled):
            return
        self.index += 1

    async def produce(self):
        try:
            while True:
                self.input_changed.clear()
                generation = self.generation
                speech = self.utterances[0] if self.utterances else None
                self.current_speech = speech
                available = speech.available_frames() if speech else 0
                if speech and speech.final and available == 0:
                    if speech.completed_at is None:
                        speech.completed_at = time.monotonic()
                    self.utterances.popleft()
                    continue
                if available <= 0:
                    self.speaking = False
                    if speech and speech.offset:
                        # Consume existing output reserve before declaring a
                        # network gap. An immediate idle frame would fabricate
                        # a pause at an otherwise continuous chunk boundary.
                        deadline = (self.clock + self.index / FPS) if self.clock is not None else time.monotonic()
                        reserve = max(0., deadline - time.monotonic() - .08)
                        if reserve > 0:
                            try:
                                await asyncio.wait_for(self.input_changed.wait(), min(.12, reserve))
                                continue
                            except asyncio.TimeoutError:  # noqa: UP041 — Python 3.10 has a distinct asyncio error.
                                if speech.cancelled or speech.available_frames() > 0:
                                    continue
                                if deadline - time.monotonic() > .08:
                                    continue
                        speech.underruns += 1
                        speech.carry.clear()
                    await self.emit(self.avatar.frame(self.index), np.zeros(SAMPLES_PER_FRAME, dtype=np.int16), generation)
                    # Keep idle production near the presentation clock instead
                    # of filling the larger speech reserve with idle frames.
                    if self.clock is not None:
                        await asyncio.sleep(max(0., self.clock + (self.index - 1) / FPS - time.monotonic()))
                    else:
                        await asyncio.sleep(1 / FPS)
                    continue
                assert speech is not None
                self.speaking = True
                if speech.offset == 0:
                    # Queue a short, explicit idle lead-in. It lets the small
                    # first batch play while the throughput batch computes.
                    for _ in range(self.batch_size + 4):
                        if speech.cancelled or generation != self.generation:
                            break
                        await self.emit(self.avatar.frame(self.index), np.zeros(SAMPLES_PER_FRAME, dtype=np.int16),
                                        generation, speech, lead=True)
                if speech.cancelled or generation != self.generation:
                    continue
                # Small first batch, then scale with available audio up to the
                # configured throughput batch. Keep every non-final batch even.
                limit = min(2, self.batch_size) if speech.offset == 0 else self.batch_size
                count = min(limit, available)
                if speech.offset == 0:
                    self.first_batches.append(count)
                async with self.lock:
                    mel, origin = await asyncio.to_thread(stream_mel, speech.pcm, speech.offset, count)
                    frames, elapsed = await asyncio.to_thread(
                        self.renderer.render_batch, self.avatar, mel, speech.offset, self.index, count,
                        speech.carry, mel_origin=origin)
                if generation != self.generation or speech.cancelled:
                    continue
                self.timings.append(elapsed * 1000 / count)
                self.rendered_frames += count
                self.render_seconds += elapsed
                for offset, frame in enumerate(frames):
                    begin = (speech.offset + offset) * SAMPLES_PER_FRAME
                    pcm = speech.pcm[begin:begin + SAMPLES_PER_FRAME]
                    if len(pcm) < SAMPLES_PER_FRAME:
                        pcm = np.pad(pcm, (0, SAMPLES_PER_FRAME - len(pcm)))
                    last = speech.final and begin + SAMPLES_PER_FRAME >= len(speech.pcm)
                    await self.emit(frame, pcm, generation, speech, last)
                speech.offset += count
                if speech.final and speech.available_frames() == 0 and self.utterances and self.utterances[0] is speech:
                    self.utterances.popleft()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = str(error)
            logger.exception("Avatar render session failed")

    def interrupt(self, source_generation: int | None = None):
        if source_generation is None:
            self.generation += 1
        else:
            self.cancelled_through = max(self.cancelled_through, source_generation)
        for speech in self.speeches.values():
            if source_generation is None or speech.source_generation <= source_generation:
                speech.cancelled = True
        self.utterances = deque(speech for speech in self.utterances if not speech.cancelled)
        self.input_changed.set()
        retained_items = []
        for queue in (self.video, self.audio):
            retained = []
            while not queue.empty():
                item = queue.get_nowait()
                if source_generation is not None and not (len(item) > 3 and item[3] and item[3][0].cancelled):
                    retained.append(item)
            retained_items.extend(retained)
            for item in retained:
                queue.put_nowait(item)
        newer_active = (source_generation is not None and self.current_speech is not None
                        and self.current_speech.source_generation > source_generation)
        newer_frames = source_generation is not None and any(
            len(item) > 3 and item[3] and item[3][0].source_generation > source_generation
            for item in retained_items + list(self.waiting.values()))
        if not newer_active and not newer_frames:
            # Reclaim cancelled slots only when no newer speech is in flight.
            # Epoch invalidates sleeping old tracks; RTP timestamps still start
            # strictly after the last index already delivered to either track.
            if source_generation is not None:
                self.generation += 1
            self.index = self.presented_index + 1
            if self.clock is not None:
                self.clock = max(self.clock, time.monotonic() - self.index / FPS)
            for queue in (self.video, self.audio):
                while not queue.empty():
                    queue.get_nowait()

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def speech_status(self, source_generation: int) -> dict:
        speech = self.speeches.get(source_generation)
        if speech is None:
            return {"state": "missing"}
        now = time.monotonic()
        return {
            "state": "cancelled" if speech.cancelled else "completed" if (
                speech.completed_at is not None and now >= speech.completed_at
            ) else "playing" if speech.started_at is not None else "buffering",
            "first_audio_ms": (speech.started_at - speech.received_at) * 1000 if speech.started_at else None,
            "received_samples": len(speech.pcm), "rendered_frames": speech.offset,
            "underrun_frames": speech.underruns, "max_audio_lateness_ms": speech.max_lateness_ms,
        }

    def metrics(self):
        return {
            "stride": self.renderer.stride, "blend": self.renderer.config.wav2lip_blend,
            "rendered_frames": self.rendered_frames, "delivered_frames": self.delivered,
            "render_fps": self.rendered_frames / self.render_seconds if self.render_seconds else None,
            "render_ms_per_frame_p95": float(np.percentile(self.timings, 95)) if self.timings else None,
            "video_queue": self.video.qsize(), "audio_queue": self.audio.qsize(),
            "speaking": self.speaking, "failure": self.failure,
            "first_batches": list(self.first_batches),
            "speeches": {str(key): self.speech_status(key) for key in self.speeches},
        }


def create_app(renderer: AvatarRenderer, asset_root: Path, avatar_id: str, batch_size: int) -> web.Application:
    allowed = {"http://127.0.0.1:3010", "http://localhost:3010"}
    peers: dict[str, tuple[RTCPeerConnection, RenderSession]] = {}
    pending_offers = 0
    lock = asyncio.Lock()
    owned_root = Path(__file__).resolve().parents[2] / ".openrealtime/avatar-renderer/avatars"
    roots = (owned_root, asset_root)
    preparation_jobs: dict[str, dict] = {}
    preparation_tasks: set[asyncio.Task] = set()

    @web.middleware
    async def access(request, handler):
        origin = request.headers.get("Origin")
        if origin and origin not in allowed:
            raise web.HTTPForbidden(text="Origin not allowed")
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except (ValueError, KeyError, wave.Error) as error:
                response = web.json_response({"code": 1, "msg": str(error)}, status=400)
            except FileNotFoundError:
                response = web.json_response({"code": 1, "msg": "Avatar has not been prepared"}, status=404)
        if origin:
            response.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                                     "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
                                     "Access-Control-Allow-Headers": "Content-Type"})
        return response

    async def offer(request):
        nonlocal pending_offers
        if len(peers) + pending_offers >= 2:
            raise web.HTTPServiceUnavailable(text="Renderer session limit reached")
        pending_offers += 1
        try:
            params = await request.json()
            selected = asset_path(roots, params.get("avatar", avatar_id))
            avatar = await asyncio.to_thread(AvatarFrames.load, selected.parent, selected.name, renderer.model_size, renderer.config.geometry)
        finally:
            pending_offers -= 1
        session = RenderSession(renderer, avatar, lock, batch_size)
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        session_id = uuid.uuid4().hex
        peers[session_id] = (peer, session)

        async def expire_unconnected():
            await asyncio.sleep(30)
            if peer.connectionState != "connected":
                await peer.close()

        expiry = asyncio.create_task(expire_unconnected())

        @peer.on("connectionstatechange")
        async def connection_changed():
            if peer.connectionState == "connected":
                expiry.cancel()
                session.start()
            elif peer.connectionState in ("failed", "closed"):
                expiry.cancel()
                peers.pop(session_id, None)
                await session.close()
                if peer.connectionState != "closed":
                    await peer.close()

        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=params["sdp"], type=params["type"]))
            peer.addTrack(OutputTrack(session, "video"))
            peer.addTrack(OutputTrack(session, "audio"))
            await peer.setLocalDescription(await peer.createAnswer())
            return web.json_response({"code": 0, "sdp": peer.localDescription.sdp,
                                      "type": "answer", "sessionid": session_id})
        except Exception:
            peers.pop(session_id, None)
            await peer.close()
            raise

    async def humanaudio(request):
        form = await request.post()
        session = peers[str(form["sessionid"])][1]
        if "generation" in form and int(form["generation"]) <= session.cancelled_through:
            return web.json_response({"code": 0, "discarded": True})
        if session.failure:
            raise web.HTTPServiceUnavailable(text=session.failure)
        pcm: np.ndarray = np.empty(0, dtype=np.int16)
        if "file" in form:
            data = form["file"].file.read(4_000_001)
            if len(data) > 4_000_000:
                raise ValueError("Audio upload too large")
            pcm = decode_wav(data)
        source_generation = int(form.get("generation", max(session.speeches, default=-1) + 1))
        session.upload(source_generation, pcm, int(form.get("sequence", 0)), form.get("final", "1") == "1")
        return web.json_response({"code": 0})

    async def audio_status(request):
        session = peers[request.query["sessionid"]][1]
        if session.failure:
            raise web.HTTPServiceUnavailable(text=session.failure)
        return web.json_response({"code": 0, **session.speech_status(int(request.query["generation"]))})

    async def interrupt(request):
        params = await request.json()
        session = peers[str(params["sessionid"])][1]
        session.interrupt(int(params["generation"]) if "generation" in params else None)
        return web.json_response({"code": 0})

    async def prepared(request):
        asset_id = request.match_info["avatar_id"]
        try:
            ready = is_prepared(asset_path(roots, asset_id), renderer.model_size)
        except FileNotFoundError:
            ready = False
        return web.json_response({"code": 0, "data": {"avatar_id": asset_id,
                                                          "state": "ready" if ready else "missing"}})

    async def prepare_task(request):
        if any(job["status"] == "running" for job in preparation_jobs.values()):
            raise web.HTTPTooManyRequests(text="An avatar is already being prepared")
        form = await request.post()
        if any(job["status"] == "running" for job in preparation_jobs.values()):
            raise web.HTTPTooManyRequests(text="An avatar is already being prepared")
        asset_id = str(form["avatar_id"])
        size = int(form["img_size"])
        if form.get("model") != "wav2lip" or size != renderer.model_size:
            raise ValueError("Preparation model does not match the renderer")
        # Validate ID before allocating any files.
        try:
            asset_path(roots, asset_id)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Avatar already exists")
        data = form["video_file"].file.read(80_000_001)
        if len(data) > 80_000_000:
            raise ValueError("Motion video exceeds 80 MB")
        task_id = str(uuid.uuid4())
        job = {"status": "running", "progress": 0}
        preparation_jobs[task_id] = job
        loop = asyncio.get_running_loop()

        async def run():
            try:
                with tempfile.TemporaryDirectory(prefix="openrealtime-prepare-") as directory:
                    source = Path(directory) / "motion.mp4"
                    source.write_bytes(data)
                    def progress(value):
                        loop.call_soon_threadsafe(job.update, {"progress": value})
                    await asyncio.to_thread(prepare, source, owned_root, asset_id, size, progress)
                job.update(status="completed", progress=100)
            except Exception as error:
                logger.exception("Avatar preparation failed")
                job.update(status="failed", error_msg=str(error))

        task = asyncio.create_task(run())
        preparation_tasks.add(task)
        task.add_done_callback(preparation_tasks.discard)
        return web.json_response({"code": 0, "data": {"task_id": task_id}})

    async def preparation_status(request):
        return web.json_response({"code": 0, "data": preparation_jobs[request.match_info["task_id"]]})

    async def health(request):
        return web.json_response({"renderer": "openrealtime", "compositor": "mouth-v2",
                                  "stride": renderer.stride, "blend": renderer.config.wav2lip_blend,
                                  "device": str(renderer.device),
                                  "sessions": {key: session.metrics() for key, (_, session) in peers.items()}})

    async def root(request):
        return web.Response(status=302, headers={"Location": "/index.html"})

    async def index(request):
        return web.Response(text="OpenRealtime Avatar Renderer", content_type="text/plain")

    async def cleanup(app):
        for peer, session in list(peers.values()):
            await session.close()
            await peer.close()
        await asyncio.gather(*preparation_tasks, return_exceptions=True)

    app = web.Application(middlewares=[access], client_max_size=81_000_000)
    app.router.add_post("/offer", offer)
    app.router.add_post("/humanaudio", humanaudio)
    app.router.add_post("/interrupt_talk", interrupt)
    app.router.add_get("/audio_status", audio_status)
    app.router.add_get("/api/avatar/prepared/{avatar_id}", prepared)
    app.router.add_post("/api/avatar/task", prepare_task)
    app.router.add_get("/api/avatar/task/{task_id}", preparation_status)
    app.router.add_get("/health", health)
    app.router.add_get("/", root)
    app.router.add_get("/index.html", index)
    app.router.add_route("OPTIONS", "/{path:.*}", index)
    app.on_cleanup.append(cleanup)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path("models/livetalking"))
    parser.add_argument("--avatar-id", default="shuchang256")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--model-size", type=int, choices=(96, 256), default=256)
    parser.add_argument("--inference-stride", type=int, choices=(1, 2), default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--blend", type=float, default=os.environ.get("OPENREALTIME_WAV2LIP_BLEND", "0.5"))
    args = parser.parse_args()
    import cv2
    import torch
    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    if not 0 <= args.blend <= 1 or not 1 <= args.batch_size <= 16 or args.batch_size % args.inference_stride:
        parser.error("Invalid blend or batch size/stride")
    repository = args.runtime_root.resolve() / "repository"
    checkpoint = repository / "models" / ("wav2lip256.pth" if args.model_size == 256 else "wav2lip.pth")
    renderer = AvatarRenderer(checkpoint, args.model_size, stride=args.inference_stride,
                              config=CompositionConfig(wav2lip_blend=args.blend))
    # Warm both the model and mel transform before opening the listening socket.
    mel_spectrogram(np.zeros(SAMPLE_RATE, dtype=np.float32))
    for _ in range(3):
        renderer.predict([np.zeros((args.model_size, args.model_size, 3), dtype=np.uint8)] * args.batch_size,
                         np.zeros((args.batch_size, 80, 16), dtype=np.float32))
    if args.inference_stride == 2:
        for key_count in range(1, args.batch_size // 2 + 2):
            for _ in range(2):
                renderer.predict([np.zeros((args.model_size, args.model_size, 3), dtype=np.uint8)] * key_count,
                                 np.zeros((key_count, 80, 16), dtype=np.float32), keyframes_only=True)
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(renderer, repository / "data/avatars", args.avatar_id, args.batch_size),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
