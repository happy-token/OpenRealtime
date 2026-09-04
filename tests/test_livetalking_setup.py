import asyncio
import hashlib
import importlib.util
import threading
from pathlib import Path

import pytest

from scripts.livetalking_provider import (
    WAV2LIP_COMPOSITOR_SHA256,
    WAV2LIP_INFERENCE_STRIDE_SHA256,
)
from scripts.setup_livetalking_runtime import (
    apply_livetalking_security_patches,
    build_livetalking_setup_plan,
    install_wav2lip_compositor,
    install_wav2lip_inference_stride,
)


def test_setup_plan_pins_livetalking_and_reuses_verified_standard_wav2lip() -> None:
    plan = build_livetalking_setup_plan(Path("models/livetalking"))

    assert plan.repository_url == "https://github.com/lipku/LiveTalking.git"
    assert plan.commit == "36837f90f8db3f59e1d7fcdd111a7db3842515d0"
    assert plan.python_version == "3.10.20"
    assert plan.model_resolution == 256
    assert plan.wav2lip_model_sha256 == (
        "a02b54288f8200332ee4f0ea0c8013bca542b94d8149e514ac25a742a7a70e66"
    )
    assert plan.lock_file.name == "livetalking-macos-arm64-py310.txt"
    locked = plan.lock_file.read_text(encoding="utf-8")
    assert "aiortc==1.15.0" in locked
    assert "torch==2.13.0" in locked


def test_install_wav2lip_compositor_replaces_hard_face_paste(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    wav2lip_package = repository / "avatars/wav2lip"
    wav2lip_package.mkdir(parents=True)
    avatar = repository / "avatars/wav2lip_avatar.py"
    avatar.write_text(
        """
from avatars.base_avatar import BaseAvatar

class LipReal(BaseAvatar):
    def paste_back_frame(self,pred_frame,idx:int):
        bbox = self.coord_list_cycle[idx]
        combine_frame = self.frame_list_cycle[idx].copy()
        y1, y2, x1, x2 = bbox
        res_frame = cv2.resize(pred_frame.astype(np.uint8),(x2-x1,y2-y1))
        combine_frame[y1:y2, x1:x2] = res_frame
        return combine_frame
""".lstrip(),
        encoding="utf-8",
    )

    install_wav2lip_compositor(repository)

    patched = avatar.read_text(encoding="utf-8")
    assert "from avatars.wav2lip.compositing import blend_wav2lip_roi" in patched
    assert "combine_frame[y1:y2, x1:x2] = blend_wav2lip_roi(" in patched
    assert "combine_frame[y1:y2, x1:x2], res_frame" in patched
    assert "combine_frame[y1:y2, x1:x2] = res_frame" not in patched
    assert (wav2lip_package / "compositing.py").read_text(encoding="utf-8") == (
        Path("scripts/wav2lip_compositing.py").read_text(encoding="utf-8")
    )
    assert hashlib.sha256((wav2lip_package / "compositing.py").read_bytes()).hexdigest() == (
        WAV2LIP_COMPOSITOR_SHA256
    )


def test_install_wav2lip_inference_stride_routes_model_calls_through_helper(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    wav2lip_package = repository / "avatars/wav2lip"
    wav2lip_package.mkdir(parents=True)
    avatar = repository / "avatars/wav2lip_avatar.py"
    avatar.write_text(
        """
from avatars.base_avatar import BaseAvatar

class LipReal(BaseAvatar):
    def inference_batch(self, index, audiofeat_batch):
        with torch.no_grad():
            pred = self.model(audiofeat_batch, img_batch)
        return pred
""".lstrip(),
        encoding="utf-8",
    )

    install_wav2lip_inference_stride(repository)

    patched = avatar.read_text(encoding="utf-8")
    assert "from avatars.wav2lip.inference_stride import infer_wav2lip_batch" in patched
    assert "inference_stride=self.opt.wav2lip_inference_stride" in patched
    assert "pred = self.model(audiofeat_batch, img_batch)" not in patched
    assert (wav2lip_package / "inference_stride.py").read_text(encoding="utf-8") == (
        Path("scripts/wav2lip_inference_stride.py").read_text(encoding="utf-8")
    )
    assert hashlib.sha256((wav2lip_package / "inference_stride.py").read_bytes()).hexdigest() == (
        WAV2LIP_INFERENCE_STRIDE_SHA256
    )


def test_security_patch_binds_loopback_limits_cors_and_disables_management_routes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    (repository / "server").mkdir(parents=True)
    (repository / "app.py").write_text(
        """
def fixture():
    appasync = web.Application(client_max_size=1024**2*100)
    appasync.router.add_get("/record/{sessionid}", download_record)
    # 注册 server/routes.py 中的通用 API 路由
    setup_routes(appasync)
    cors = aiohttp_cors.setup(appasync, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        })
    # Configure CORS on all routes.
    for route in list(appasync.router.routes()):
        cors.add(route)
    whep_resource = appasync.router.add_resource('/whep')
    whep_resource.add_route('POST', whep)
    whep_resource.add_route('OPTIONS', lambda _: web.Response(status=200))
    logger.info('start http server; http://<serverip>:'+str(opt.listenport))
        site = web.TCPSite(runner, '0.0.0.0', opt.listenport)
""".strip(),
        encoding="utf-8",
    )
    (repository / "server/routes.py").write_text(
        """
import json

    app.router.add_post("/set_audiotype", set_audiotype)
    app.router.add_post("/record", record)
    app.router.add_get("/api/admin/config", admin_config)
    app.router.add_get("/api/admin/sessions", admin_sessions)
    app.router.add_get('/sse', sse_handler)
    # ── Local ASR endpoint (SenseVoice/FunASR) ── Issue #604 ──
    pass
    # 注册 avatar 生成相关的路由
    setup_avatar_routes(app)
    app.router.add_static('/', path='web')
""".strip(),
        encoding="utf-8",
    )
    (repository / "server/avatar_routes.py").write_text(
        '''
import json
import os
import uuid

async def create_avatar_task(request):
        filename = part.filename
        if not model_type or not avatar_id:
            return json_error("model and avatar_id are required")
        if not os.path.isabs(video_path):
            video_path = os.path.join(data_path, video_path)

        save_path = data_path

async def list_avatar_tasks(request):
    pass

async def delete_avatar_task(request):
    pass

def setup_avatar_routes(app):
    app.router.add_get("/api/avatar/tasks", list_avatar_tasks)
'''.strip(),
        encoding="utf-8",
    )
    (repository / "server/rtc_manager.py").write_text(
        """
        params = dict(request.query)
            sessionid = await session_manager.create_session(params)
        # 客户端可通过 query param 自定义 sessionid，不传则自动生成
        client_sid = params.pop("sessionid", None)
            sessionid = await session_manager.create_session(params, sessionid=client_sid)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return pc
""".strip(),
        encoding="utf-8",
    )
    (repository / "avatars/audio_features").mkdir(parents=True)
    (repository / "streamout").mkdir()
    (repository / "avatars/base_avatar.py").write_text(
        """
from threading import Thread, Event

@dataclass
class AudioFrameData:
    data: NDArray[np.float32]
    type: int = 0  # 默认值
    userdata: dict = field(default_factory=dict)

        self.speaking = False
        self.recording = False

    def flush_talk(self):
        if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
            self.tts.flush_talk()
        if hasattr(self, 'asr') and hasattr(self.asr, 'flush_talk'):
            self.asr.flush_talk()
        self.custom_audiotype = 0

                audio_frames.append(audioframe)

             # 检测状态变化
            current_speaking = not is_all_silence

            # 检测状态变化
            current_speaking = not (audio_frames[0].type!=0 and audio_frames[1].type!=0)

            # 使用统一输出接口推送视频帧
            self.output.push_video_frame(combine_frame)
            self.record_video_data(combine_frame)

            for audio_frame in audio_frames:
                #frame,type,eventpoint = audio_frame
                frame = (audio_frame.data * 32767).astype(np.int16)

                # 使用统一输出接口推送音频帧
                self.output.push_audio_frame(frame, audio_frame.userdata)
                self.record_audio_data(frame)

        cmd_combine_audio = f"ffmpeg -y -i {temp_aac} -i {temp_mp4} -c:v copy -c:a copy {output_file}"
        os.system(cmd_combine_audio)
""".strip(),
        encoding="utf-8",
    )
    (repository / "avatars/audio_features/base_asr.py").write_text(
        """
    def put_audio_frame(self,audio_chunk:NDArray[np.float32],datainfo:dict):
        self.queue.put(AudioFrameData(data=audio_chunk,type=0,userdata=datainfo))

                return AudioFrameData(data=frame, type=type, userdata={})

            return AudioFrameData(data=frame, type=1, userdata={})

    def flush_talk(self):
        self.queue.queue.clear()
""".strip(),
        encoding="utf-8",
    )
    (repository / "server/webrtc.py").write_text(
        """
import queue

class HumanPlayer:
    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self.__video._queue.put((new_frame, None))

    def push_audio(self, frame, eventpoint=None):
        from av import AudioFrame
        new_frame = AudioFrame(format='s16', layout='mono', samples=frame.shape[0])
        new_frame.planes[0].update(frame.tobytes())
        new_frame.sample_rate = 16000
        self.__audio._queue.put((new_frame, eventpoint))

    def get_buffer_size(self) -> int:
        return self.__video._queue.qsize()

    def notify(self,eventpoint):
        pass
""".strip(),
        encoding="utf-8",
    )
    (repository / "streamout/webrtc.py").write_text(
        """
class WebRTCOutput:
    def get_buffer_size(self) -> int:
        if self._player and hasattr(self._player, 'get_buffer_size'):
            return self._player.get_buffer_size()
        return 0

    def stop(self) -> None:
        pass
""".strip(),
        encoding="utf-8",
    )
    (repository / "server/session_manager.py").write_text(
        """
import asyncio

class SessionManager:
    def __init__(self):
        if not hasattr(self, "initialized"):
            self.sessions: Dict[str, BaseAvatar] = {}
            self.build_session_fn = None

    async def create_session(self, params: dict, sessionid: str = None) -> str:
        if self.build_session_fn is None:
            raise Exception("SessionManager builder not initialized")
        if sessionid is None:
            sessionid = _rand_session_id()
        active_count = sum(1 for s in self.sessions.values() if s is not None)
        if active_count >= self.max_session:
            raise MaxSessionError(
                f"Maximum session limit reached ({active_count}/{self.max_session})"
            )
        logger.info('Creating sessionid=%s, current session num=%d', sessionid, active_count)
        self.sessions[sessionid] = None
        avatar_session = await asyncio.get_event_loop().run_in_executor(
            None, self.build_session_fn, sessionid, params
        )
        self.sessions[sessionid] = avatar_session
        return sessionid

    def add_session(self, sessionid: str, avatar_session: BaseAvatar):
        self.sessions[sessionid] = avatar_session
""".strip(),
        encoding="utf-8",
    )

    apply_livetalking_security_patches(repository)

    app_source = (repository / "app.py").read_text(encoding="utf-8")
    route_source = (repository / "server/routes.py").read_text(encoding="utf-8")
    avatar_route_source = (repository / "server/avatar_routes.py").read_text(
        encoding="utf-8"
    )
    assert "LIVETALKING_BIND_HOST" in app_source
    assert "LIVETALKING_ALLOWED_ORIGINS" in app_source
    assert "enforce_allowed_origin" in app_source
    assert '"*": aiohttp_cors.ResourceOptions' not in app_source
    assert 'add_post("/whep", whep)' in app_source
    assert 'expose_headers=("Content-Type", "X-Session-ID")' in app_source
    assert "lambda _: web.Response" not in app_source
    assert 'add_get("/record/' not in app_source
    assert "LIVETALKING_ENABLE_MANAGEMENT_ROUTES" in route_source
    assert "LIVETALKING_WAV2LIP_MODEL_SIZE" in avatar_route_source
    assert "manifest.get('face_size') == expected_face_size" in avatar_route_source
    assert "manifest.get('face_size') == 96" not in avatar_route_source
    rtc_source = (repository / "server/rtc_manager.py").read_text(encoding="utf-8")
    avatar_source = (repository / "avatars/base_avatar.py").read_text(encoding="utf-8")
    assert "dict(request.query)" not in rtc_source
    assert "client_sid" not in rtc_source
    assert "create_session({})" in rtc_source
    assert "self.pcs.discard(pc)" in rtc_source
    assert "session_manager.remove_session(sessionid)" in rtc_source
    assert "os.system" not in avatar_source
    assert "subprocess.run([" in avatar_source
    assert "shell=False" in avatar_source
    assert "self._talk_generation += 1" in avatar_source
    assert avatar_source.count("frame.generation != self._talk_generation") == 3
    assert "self._talk_lock = Lock()" in avatar_source
    assert "with self._talk_lock:" in avatar_source
    assert "continue  # The interrupt invalidated this batch before publication." in avatar_source
    flush_start = avatar_source.index("    def flush_talk(self):")
    flush_source = avatar_source[
        flush_start : avatar_source.index(
            "                audio_frames.append(audioframe)", flush_start
        )
    ]
    assert "self.speaking = False" not in flush_source
    asr_source = (repository / "avatars/audio_features/base_asr.py").read_text(encoding="utf-8")
    assert "generation=self.parent._talk_generation" in asr_source
    assert "with self.queue.mutex" in asr_source
    player_source = (repository / "server/webrtc.py").read_text(encoding="utf-8")
    assert "def flush_pending(self)" in player_source
    assert "put_nowait" in player_source
    assert "except queue.Full" in player_source
    player_spec = importlib.util.spec_from_file_location(
        "patched_livetalking_webrtc",
        repository / "server/webrtc.py",
    )
    assert player_spec is not None and player_spec.loader is not None
    player_module = importlib.util.module_from_spec(player_spec)
    player_spec.loader.exec_module(player_module)
    track = type("Track", (), {})()
    track._queue = player_module.queue.Queue(maxsize=1)
    track._queue.put_nowait("stale")
    player_module.HumanPlayer._enqueue_latest(track, "latest")
    assert track._queue.get_nowait() == "latest"
    output_source = (repository / "streamout/webrtc.py").read_text(encoding="utf-8")
    assert "self._player.flush_pending()" in output_source
    session_source = (repository / "server/session_manager.py").read_text(encoding="utf-8")
    assert "async with self._capacity_lock" in session_source
    assert "active_count = len(self.sessions)" in session_source
    assert "self.sessions.pop(sessionid, None)" in session_source
    assert "except BaseException:" in session_source
    assert "await asyncio.shield(build_future)" in session_source
    assert "_finish_cancelled_build" in session_source

    first_snapshot = {path: path.read_bytes() for path in repository.rglob("*.py")}
    apply_livetalking_security_patches(repository)
    assert first_snapshot == {path: path.read_bytes() for path in repository.rglob("*.py")}


@pytest.mark.asyncio
async def test_cancelled_session_build_releases_reserved_capacity(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "server").mkdir(parents=True)
    session_path = repository / "server/session_manager.py"
    session_path.write_text(
        """
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, BaseAvatar] = {}
        self.build_session_fn = None

    async def create_session(self, params: dict, sessionid: str = None) -> str:
        raise NotImplementedError

    def add_session(self, sessionid: str, avatar_session: BaseAvatar):
        self.sessions[sessionid] = avatar_session
""".strip(),
        encoding="utf-8",
    )
    # Only the session manager portion is needed for this behavioral regression.
    source = session_path.read_text(encoding="utf-8")
    old = "        self.sessions: Dict[str, BaseAvatar] = {}\n        self.build_session_fn = None"
    source = source.replace(
        old,
        "        self.sessions: Dict[str, BaseAvatar] = {}\n"
        "        self._capacity_lock = asyncio.Lock()\n"
        "        self._cleanup_tasks = set()\n"
        "        self.build_session_fn = None",
    )
    method_start = source.index("    async def create_session(")
    method_end = source.index("\n    def add_session", method_start)
    # Reuse the production patch to obtain the exact method without importing upstream code.
    production_source = Path("scripts/setup_livetalking_runtime.py").read_text(encoding="utf-8")
    marker = "    canonical_method = '''"
    canonical_start = production_source.index(marker) + len(marker)
    canonical_end = production_source.index("'''\n    session_manager.write_text", canonical_start)
    source = (
        source[:method_start]
        + production_source[canonical_start:canonical_end]
        + source[method_end:]
    )
    source = (
        """
import asyncio
from typing import Dict

class BaseAvatar:
    pass

class MaxSessionError(Exception):
    pass

def _rand_session_id():
    return "generated"

class Logger:
    def info(self, *args):
        pass

    def exception(self, *args):
        pass

logger = Logger()

"""
        + source
    )
    session_path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("cancel_session_fixture", session_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manager = module.SessionManager()
    manager.max_session = 1
    release_builder = threading.Event()
    builder_started = threading.Event()

    stopped = threading.Event()

    class Output:
        def stop(self) -> None:
            stopped.set()

    class Avatar:
        output = Output()

    def blocking_builder(sessionid: str, params: dict[str, object]) -> object:
        builder_started.set()
        release_builder.wait(timeout=2)
        return Avatar()

    manager.build_session_fn = blocking_builder
    task = asyncio.create_task(manager.create_session({}, sessionid="cancelled"))
    await asyncio.to_thread(builder_started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.sessions == {"cancelled": None}

    with pytest.raises(module.MaxSessionError):
        await manager.create_session({}, sessionid="too-early")

    release_builder.set()
    await asyncio.wait_for(asyncio.to_thread(stopped.wait, 1), timeout=2)
    for _ in range(100):
        if manager.sessions == {}:
            break
        await asyncio.sleep(0.01)
    assert manager.sessions == {}
    manager.build_session_fn = lambda sessionid, params: object()
    assert await manager.create_session({}, sessionid="replacement") == "replacement"

    # Cancellation while waiting to publish a completed build must take the same cleanup path.
    manager.sessions.clear()
    release_publish_builder = threading.Event()
    publish_builder_started = threading.Event()
    publish_builder_finished = threading.Event()
    publish_stopped = threading.Event()

    class PublishOutput:
        def stop(self) -> None:
            publish_stopped.set()

    class PublishAvatar:
        output = PublishOutput()

    def publish_builder(sessionid: str, params: dict[str, object]) -> object:
        publish_builder_started.set()
        release_publish_builder.wait(timeout=2)
        publish_builder_finished.set()
        return PublishAvatar()

    manager.build_session_fn = publish_builder
    publish_task = asyncio.create_task(manager.create_session({}, sessionid="publish-race"))
    await asyncio.to_thread(publish_builder_started.wait, 1)
    await manager._capacity_lock.acquire()
    try:
        release_publish_builder.set()
        await asyncio.to_thread(publish_builder_finished.wait, 1)
        await asyncio.sleep(0)
        assert not publish_task.done()
        publish_task.cancel()
    finally:
        manager._capacity_lock.release()
    with pytest.raises(asyncio.CancelledError):
        await publish_task
    await asyncio.wait_for(asyncio.to_thread(publish_stopped.wait, 1), timeout=2)
    for _ in range(100):
        if manager.sessions == {}:
            break
        await asyncio.sleep(0.01)
    assert manager.sessions == {}
