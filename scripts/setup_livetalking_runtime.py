"""Install a pinned LiveTalking WebRTC runtime backed by Wav2Lip 256 by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.livetalking_provider import (
    LIVETALKING_COMMIT,
    LIVETALKING_PATCH_DIFF_SHA256,
    LIVETALKING_REPOSITORY_URL,
    LiveTalkingRuntime,
    inspect_livetalking_runtime,
)

MINIMUM_FREE_BYTES = 4 * 1024**3
WAV2LIP_MODEL_SOURCE_SHA256 = "a02b54288f8200332ee4f0ea0c8013bca542b94d8149e514ac25a742a7a70e66"
WAV2LIP_CHECKPOINT_SHA256 = "b78b681b68ad9fe6c6fb1debc6ff43ad05834a8af8a62ffc4167b7b34ef63c37"
WAV2LIP256_CHECKPOINT_SHA256 = "b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173"
PREVIOUS_LIVETALKING_PATCH_DIFF_SHA256 = (
    "50321687b54775540221554c0811bc01c7059e28bce22ef6e277fbe073cc922c"
)


@dataclass(frozen=True)
class LiveTalkingSetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    python_version: str
    minimum_free_bytes: int
    model_resolution: int
    wav2lip_model_sha256: str
    lock_file: Path


def build_livetalking_setup_plan(runtime_root: Path) -> LiveTalkingSetupPlan:
    return LiveTalkingSetupPlan(
        runtime_root=runtime_root,
        repository_url=LIVETALKING_REPOSITORY_URL,
        commit=LIVETALKING_COMMIT,
        python_version="3.10.20",
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        model_resolution=256,
        wav2lip_model_sha256=WAV2LIP_MODEL_SOURCE_SHA256,
        lock_file=Path(__file__).with_name("locks") / "livetalking-macos-arm64-py310.txt",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_required(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content and new not in old:
        return
    if old in content:
        path.write_text(content.replace(old, new), encoding="utf-8")
        return
    if new not in content:
        raise RuntimeError(f"LiveTalking compatibility patch no longer applies: {path}: {old!r}")


def _replace_optional(path: Path, old: str, new: str) -> None:
    """Patch an upstream module only when that optional module is installed."""
    if path.exists():
        _replace_required(path, old, new)


def _replace_any_required(path: Path, old_values: tuple[str, ...], new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content:
        return
    for old in old_values:
        if old in content:
            path.write_text(content.replace(old, new), encoding="utf-8")
            return
    raise RuntimeError(f"LiveTalking compatibility patch no longer applies: {path}")


def _ensure_import(path: Path, module: str) -> None:
    content = path.read_text(encoding="utf-8")
    statement = f"import {module}\n"
    if statement not in content:
        path.write_text(statement + content, encoding="utf-8")


def _ensure_from_import(path: Path, statement: str, *, after: str) -> None:
    content = path.read_text(encoding="utf-8")
    line = f"{statement}\n"
    if line in content:
        return
    anchor = f"{after}\n"
    if anchor not in content:
        raise RuntimeError(f"Import anchor is missing: {path}: {after}")
    path.write_text(content.replace(anchor, anchor + line, 1), encoding="utf-8")


def _replace_version_optional(path: Path, old: str, new: str) -> None:
    """Apply a patch introduced only in newer upstream layouts."""
    content = path.read_text(encoding="utf-8")
    if old in content or new in content:
        _replace_required(path, old, new)


def install_wav2lip_compositor(repository: Path) -> None:
    """Install the project-owned soft compositor into a LiveTalking checkout."""

    source = Path(__file__).with_name("wav2lip_compositing.py")
    destination = repository / "avatars/wav2lip/compositing.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    avatar = repository / "avatars/wav2lip_avatar.py"
    _ensure_from_import(
        avatar,
        "from avatars.wav2lip.compositing import blend_wav2lip_roi",
        after="from avatars.base_avatar import BaseAvatar",
    )
    _replace_required(
        avatar,
        "        combine_frame[y1:y2, x1:x2] = res_frame",
        "        combine_frame[y1:y2, x1:x2] = blend_wav2lip_roi(\n"
        "            combine_frame[y1:y2, x1:x2], res_frame\n"
        "        )",
    )


def install_wav2lip_inference_stride(repository: Path) -> None:
    """Install frame-strided inference while keeping a full-rate output batch."""

    source = Path(__file__).with_name("wav2lip_inference_stride.py")
    destination = repository / "avatars/wav2lip/inference_stride.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    avatar = repository / "avatars/wav2lip_avatar.py"
    _ensure_from_import(
        avatar,
        "from avatars.wav2lip.inference_stride import infer_wav2lip_batch",
        after="from avatars.base_avatar import BaseAvatar",
    )
    _replace_required(
        avatar,
        "            pred = self.model(audiofeat_batch, img_batch)",
        "            pred = infer_wav2lip_batch(\n"
        "                self.model, audiofeat_batch, img_batch,\n"
        "                inference_stride=self.opt.wav2lip_inference_stride,\n"
        "            )",
    )


def apply_livetalking_security_patches(repository: Path) -> None:
    """Restrict the bundled HTTP service to the local evaluation surface."""

    app = repository / "app.py"
    _replace_required(
        app,
        "    appasync = web.Application(client_max_size=1024**2*100)",
        """    allowed_origins = {
        origin.strip()
        for origin in os.environ.get("LIVETALKING_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }

    @web.middleware
    async def enforce_allowed_origin(request, handler):
        if request.headers.get("Origin") not in allowed_origins:
            raise web.HTTPForbidden(text="Origin is not allowed")
        return await handler(request)

    appasync = web.Application(
        client_max_size=1024**2*100,
        middlewares=[enforce_allowed_origin],
    )""",
    )
    _replace_required(
        app,
        'appasync.router.add_get("/record/{sessionid}", download_record)',
        "# Recording downloads are disabled in the local evaluation launcher.",
    )
    app_source = app.read_text(encoding="utf-8")
    cors_start = app_source.index("    # 注册 server/routes.py 中的通用 API 路由")
    cors_end = app_source.index("\n    logger.info('start http server", cors_start)
    canonical_cors_block = textwrap.dedent(
        """
        # 注册 server/routes.py 中的通用 API 路由
        setup_routes(appasync)
        appasync.router.add_post("/whep", whep)

        # CORS and the origin middleware use the same strict local allowlist.
        cors = aiohttp_cors.setup(appasync, defaults={
            origin: aiohttp_cors.ResourceOptions(
                allow_credentials=False,
                expose_headers=("Content-Type", "X-Session-ID"),
                allow_headers=("Content-Type",),
            )
            for origin in allowed_origins
        })
        for route in list(appasync.router.routes()):
            cors.add(route)
        """
    ).strip("\n")
    canonical_cors_block = textwrap.indent(canonical_cors_block, "    ")
    app.write_text(
        app_source[:cors_start] + canonical_cors_block + app_source[cors_end:],
        encoding="utf-8",
    )
    _replace_required(
        app,
        "web.TCPSite(runner, '0.0.0.0', opt.listenport)",
        """web.TCPSite(
            runner,
            os.environ.get("LIVETALKING_BIND_HOST", "127.0.0.1"),
            opt.listenport,
        )""",
    )

    routes = repository / "server/routes.py"
    _replace_required(routes, "import json\n", "import json\nimport os\n")
    route_source = routes.read_text(encoding="utf-8")
    route_anchor = '    app.router.add_post("/set_audiotype", set_audiotype)\n'
    route_start = route_source.index(route_anchor) + len(route_anchor)
    route_end = route_source.index("\n    # ── Local ASR endpoint", route_start)
    route_prefix = """    if os.environ.get("LIVETALKING_ENABLE_MANAGEMENT_ROUTES") == "1":
        app.router.add_post("/record", record)
    app.router.add_post("/interrupt_talk", interrupt_talk)
    app.router.add_post("/is_speaking", is_speaking)
    if os.environ.get("LIVETALKING_ENABLE_MANAGEMENT_ROUTES") == "1":
        app.router.add_get("/api/admin/config", admin_config)
        app.router.add_get("/api/admin/sessions", admin_sessions)
        app.router.add_get('/sse', sse_handler)"""
    route_source = route_source[:route_start] + route_prefix + route_source[route_end:]
    avatar_start = route_source.index("    # 注册 avatar 生成相关的路由")
    route_source = (
        route_source[:avatar_start]
        + """    # 注册 avatar 生成相关的路由
    if os.environ.get("LIVETALKING_ENABLE_AVATAR_PREPARATION_ROUTES") == "1":
        setup_avatar_routes(app)
    if os.environ.get("LIVETALKING_ENABLE_MANAGEMENT_ROUTES") == "1":
        app.router.add_static('/', path='web')
"""
    )
    routes.write_text(route_source, encoding="utf-8")

    avatar_routes = repository / "server/avatar_routes.py"
    _replace_optional(avatar_routes, "import uuid\n", "import uuid\nimport re\nfrom pathlib import Path\n")
    _replace_optional(avatar_routes, "filename = part.filename", "filename = os.path.basename(part.filename or 'avatar.mp4')")
    _replace_optional(
        avatar_routes,
        """        if not model_type or not avatar_id:
            return json_error("model and avatar_id are required")""",
        """        if not model_type or not avatar_id:
            return json_error("model and avatar_id are required")
        if model_type != "wav2lip":
            return json_error("unsupported avatar model")
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", avatar_id) is None:
            return json_error("invalid avatar_id")""",
    )
    _replace_optional(
        avatar_routes,
        """        if not os.path.isabs(video_path):
            video_path = os.path.join(data_path, video_path)

        save_path = data_path""",
        """        if not os.path.isabs(video_path):
            video_path = os.path.join(data_path, video_path)
        resolved_video = Path(video_path).resolve()
        allowed_roots = [
            Path(item).resolve()
            for item in os.environ.get("LIVETALKING_AVATAR_SOURCE_ROOTS", "").split(os.pathsep)
            if item
        ]
        if not resolved_video.is_file() or not any(
            resolved_video == root or resolved_video.is_relative_to(root)
            for root in allowed_roots
        ):
            return json_error("video_path is outside configured avatar source roots")
        video_path = str(resolved_video)

        save_path = data_path""",
    )
    _replace_optional(
        avatar_routes,
        """async def delete_avatar_task(request):""",
        """async def get_prepared_avatar(request):
    avatar_id = request.match_info.get('avatar_id', '')
    if re.fullmatch(r\"[a-z0-9][a-z0-9_-]{0,63}\", avatar_id) is None:
        return json_error(\"invalid avatar_id\")
    avatar_root = (Path('./data/avatars') / avatar_id).resolve()
    try:
        expected_face_size = int(os.environ.get('LIVETALKING_WAV2LIP_MODEL_SIZE', '96'))
        if expected_face_size not in (96, 256):
            raise ValueError('invalid Wav2Lip model size')
        manifest = json.loads((avatar_root / 'manifest.json').read_text(encoding='utf-8'))
        ready = (
            manifest.get('schema_version') == 1
            and manifest.get('avatar_id') == avatar_id
            and manifest.get('fps') == 25
            and manifest.get('face_size') == expected_face_size
            and manifest.get('rights_confirmed') is True
            and (avatar_root / 'coords.json').is_file()
            and (avatar_root / 'full_imgs/00000000.png').is_file()
            and (avatar_root / 'face_imgs/00000000.png').is_file()
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        ready = False
    return json_ok(data={\"state\": \"ready\" if ready else \"missing\", \"avatar_id\": avatar_id})

async def delete_avatar_task(request):""",
    )
    _replace_optional(
        avatar_routes,
        '    app.router.add_get("/api/avatar/tasks", list_avatar_tasks)',
        '    app.router.add_get("/api/avatar/tasks", list_avatar_tasks)\n    app.router.add_get("/api/avatar/prepared/{avatar_id}", get_prepared_avatar)',
    )

    task_manager = repository / "server/task_manager.py"
    _replace_optional(
        task_manager,
        """    def add_task(self, model_type, avatar_id, params, task_id=None, notify_url=None):
        if task_id is None:
            task_id = str(uuid.uuid4())

        task = AvatarTask(task_id, model_type, avatar_id, params, notify_url)
        with self.lock:
            self.tasks[task_id] = task""",
        """    def add_task(self, model_type, avatar_id, params, task_id=None, notify_url=None):
        with self.lock:
            existing = next((
                task for task in self.tasks.values()
                if task.model_type == model_type
                and task.avatar_id == avatar_id
                and task.status in {"pending", "running"}
            ), None)
            if existing:
                return existing.task_id
            if task_id is None:
                task_id = str(uuid.uuid4())
            task = AvatarTask(task_id, model_type, avatar_id, params, notify_url)
            self.tasks[task_id] = task""",
    )

    rtc_manager = repository / "server/rtc_manager.py"
    _ensure_import(rtc_manager, "re")
    _replace_version_optional(
        rtc_manager,
        """        try:
            sessionid = await session_manager.create_session(params)""",
        """        avatar_id = params.get(\"avatar\")
        if avatar_id is not None and (
            not isinstance(avatar_id, str)
            or re.fullmatch(r\"[a-z0-9][a-z0-9_-]{0,63}\", avatar_id) is None
        ):
            return web.Response(
                status=400,
                content_type=\"application/json\",
                text=json.dumps({\"code\": -1, \"msg\": \"invalid avatar\"}),
            )
        session_params = {\"avatar\": avatar_id} if avatar_id else {}

        try:
            sessionid = await session_manager.create_session(session_params)""",
    )
    _replace_required(
        rtc_manager,
        "params = dict(request.query)",
        "params = {}  # The local launcher does not accept per-request path/config overrides.",
    )
    _replace_required(
        rtc_manager,
        """# 客户端可通过 query param 自定义 sessionid，不传则自动生成
        client_sid = params.pop("sessionid", None)""",
        "# Session IDs are always generated by the server.",
    )
    _replace_required(
        rtc_manager,
        "sessionid = await session_manager.create_session(params, sessionid=client_sid)",
        "sessionid = await session_manager.create_session({})  # Server-generated WHEP session.",
    )
    _replace_required(
        rtc_manager,
        """await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return pc""",
        """try:
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            return pc
        except Exception:
            await pc.close()
            self.pcs.discard(pc)
            session_manager.remove_session(sessionid)
            raise""",
    )

    base_avatar = repository / "avatars/base_avatar.py"
    _replace_required(
        base_avatar,
        "from threading import Thread, Event",
        "from threading import Thread, Event, Lock",
    )
    _replace_required(
        base_avatar,
        """cmd_combine_audio = f"ffmpeg -y -i {temp_aac} -i {temp_mp4} -c:v copy -c:a copy {output_file}"
        os.system(cmd_combine_audio)""",
        """subprocess.run([
            "ffmpeg", "-y", "-i", temp_aac, "-i", temp_mp4,
            "-c:v", "copy", "-c:a", "copy", output_file,
        ], check=True, shell=False)""",
    )
    _replace_required(
        base_avatar,
        """@dataclass
class AudioFrameData:
    data: NDArray[np.float32]
    type: int = 0  # 默认值
    userdata: dict = field(default_factory=dict)""",
        """@dataclass
class AudioFrameData:
    data: NDArray[np.float32]
    type: int = 0  # 默认值
    userdata: dict = field(default_factory=dict)
    generation: int = 0""",
    )
    _replace_required(
        base_avatar,
        """        self.speaking = False
        self.recording = False""",
        """        self.speaking = False
        self._talk_generation = 0
        self._talk_lock = Lock()
        self.recording = False""",
    )
    _replace_required(
        base_avatar,
        """    def flush_talk(self):
        if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
            self.tts.flush_talk()
        if hasattr(self, 'asr') and hasattr(self.asr, 'flush_talk'):
            self.asr.flush_talk()
        self.custom_audiotype = 0""",
        """    def flush_talk(self):
        with self._talk_lock:
            self._talk_generation += 1
            if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
                self.tts.flush_talk()
            if hasattr(self, 'asr') and hasattr(self.asr, 'flush_talk'):
                self.asr.flush_talk()
            with self.res_frame_queue.mutex:
                self.res_frame_queue.queue.clear()
                self.res_frame_queue.not_full.notify_all()
            if hasattr(self, 'output') and hasattr(self.output, 'flush_pending'):
                self.output.flush_pending()
            self.custom_audiotype = 0""",
    )
    _replace_required(
        base_avatar,
        """                audio_frames.append(audioframe)

             # 检测状态变化
            current_speaking = not is_all_silence""",
        """                audio_frames.append(audioframe)

            if any(frame.generation != self._talk_generation for frame in audio_frames):
                audio_frames = [
                    AudioFrameData(
                        data=np.zeros_like(frame.data),
                        type=1,
                        generation=self._talk_generation,
                    )
                    for frame in audio_frames
                ]
                is_all_silence = True

             # 检测状态变化
            current_speaking = not is_all_silence""",
    )
    _replace_required(
        base_avatar,
        """            # 检测状态变化
            current_speaking = not (audio_frames[0].type!=0 and audio_frames[1].type!=0)""",
        """            if any(frame.generation != self._talk_generation for frame in audio_frames):
                audio_frames = [
                    AudioFrameData(
                        data=np.zeros_like(frame.data),
                        type=1,
                        generation=self._talk_generation,
                    )
                    for frame in audio_frames
                ]
                res_frame = None

            # 检测状态变化
            current_speaking = not (audio_frames[0].type!=0 and audio_frames[1].type!=0)""",
    )
    _replace_required(
        base_avatar,
        """            # 使用统一输出接口推送视频帧
            self.output.push_video_frame(combine_frame)
            self.record_video_data(combine_frame)

            for audio_frame in audio_frames:
                #frame,type,eventpoint = audio_frame
                frame = (audio_frame.data * 32767).astype(np.int16)

                # 使用统一输出接口推送音频帧
                self.output.push_audio_frame(frame, audio_frame.userdata)
                self.record_audio_data(frame)""",
        """            with self._talk_lock:
                if any(frame.generation != self._talk_generation for frame in audio_frames):
                    continue  # The interrupt invalidated this batch before publication.
                # 使用统一输出接口推送视频帧
                self.output.push_video_frame(combine_frame)
                self.record_video_data(combine_frame)

                for audio_frame in audio_frames:
                    frame = (audio_frame.data * 32767).astype(np.int16)
                    # 使用统一输出接口推送音频帧
                    self.output.push_audio_frame(frame, audio_frame.userdata)
                    self.record_audio_data(frame)""",
    )

    base_asr = repository / "avatars/audio_features/base_asr.py"
    _replace_required(
        base_asr,
        "self.queue.put(AudioFrameData(data=audio_chunk,type=0,userdata=datainfo))",
        """self.queue.put(AudioFrameData(
            data=audio_chunk,
            type=0,
            userdata=datainfo,
            generation=self.parent._talk_generation if self.parent else 0,
        ))""",
    )
    _replace_required(
        base_asr,
        "return AudioFrameData(data=frame, type=type, userdata={})",
        """return AudioFrameData(
                    data=frame,
                    type=type,
                    userdata={},
                    generation=self.parent._talk_generation if self.parent else 0,
                )""",
    )
    _replace_required(
        base_asr,
        "return AudioFrameData(data=frame, type=1, userdata={})",
        """return AudioFrameData(
                data=frame,
                type=1,
                userdata={},
                generation=self.parent._talk_generation if self.parent else 0,
            )""",
    )
    _replace_required(
        base_asr,
        """    def flush_talk(self):
        self.queue.queue.clear()""",
        """    def flush_talk(self):
        with self.queue.mutex:
            self.queue.queue.clear()
            self.queue.not_full.notify_all()""",
    )

    webrtc_player = repository / "server/webrtc.py"
    _replace_required(
        webrtc_player,
        """    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self.__video._queue.put((new_frame, None))

    def push_audio(self, frame, eventpoint=None):
        from av import AudioFrame
        new_frame = AudioFrame(format='s16', layout='mono', samples=frame.shape[0])
        new_frame.planes[0].update(frame.tobytes())
        new_frame.sample_rate = 16000
        self.__audio._queue.put((new_frame, eventpoint))""",
        """    @staticmethod
    def _enqueue_latest(track, item) -> None:
        \"\"\"Publish without blocking; discard one stale item when the queue is full.\"\"\"
        try:
            track._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            track._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            track._queue.put_nowait(item)
        except queue.Full:
            mylogger.warning("Dropping media frame because the WebRTC queue stayed full")

    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self._enqueue_latest(self.__video, (new_frame, None))

    def push_audio(self, frame, eventpoint=None):
        from av import AudioFrame
        new_frame = AudioFrame(format='s16', layout='mono', samples=frame.shape[0])
        new_frame.planes[0].update(frame.tobytes())
        new_frame.sample_rate = 16000
        self._enqueue_latest(self.__audio, (new_frame, eventpoint))""",
    )
    _replace_required(
        webrtc_player,
        """    def get_buffer_size(self) -> int:
        return self.__video._queue.qsize()

    def notify(self,eventpoint):""",
        """    def get_buffer_size(self) -> int:
        return self.__video._queue.qsize()

    def flush_pending(self) -> None:
        for track in (self.__audio, self.__video):
            with track._queue.mutex:
                track._queue.queue.clear()
                track._queue.not_full.notify_all()

    def notify(self,eventpoint):""",
    )

    webrtc_output = repository / "streamout/webrtc.py"
    _replace_required(
        webrtc_output,
        """    def get_buffer_size(self) -> int:
        if self._player and hasattr(self._player, 'get_buffer_size'):
            return self._player.get_buffer_size()
        return 0

    def stop(self) -> None:""",
        """    def get_buffer_size(self) -> int:
        if self._player and hasattr(self._player, 'get_buffer_size'):
            return self._player.get_buffer_size()
        return 0

    def flush_pending(self) -> None:
        if self._player and hasattr(self._player, 'flush_pending'):
            self._player.flush_pending()

    def stop(self) -> None:""",
    )

    session_manager = repository / "server/session_manager.py"
    session_initialization = session_manager.read_text(encoding="utf-8")
    previous_initialization = """            self.sessions: Dict[str, BaseAvatar] = {}
            self._capacity_lock = asyncio.Lock()
            self.build_session_fn = None"""
    original_initialization = """            self.sessions: Dict[str, BaseAvatar] = {}
            self.build_session_fn = None"""
    hardened_initialization = """            self.sessions: Dict[str, BaseAvatar] = {}
            self._capacity_lock = asyncio.Lock()
            self._cleanup_tasks = set()
            self.build_session_fn = None"""
    if hardened_initialization not in session_initialization:
        _replace_required(
            session_manager,
            previous_initialization
            if previous_initialization in session_initialization
            else original_initialization,
            hardened_initialization,
        )
    session_source = session_manager.read_text(encoding="utf-8")
    method_start = session_source.index("    async def create_session(")
    method_end = session_source.index("\n    def add_session", method_start)
    canonical_method = '''    async def create_session(self, params: dict, sessionid: str = None) -> str:
        """Reserve capacity atomically, then build the session off the event loop."""
        if self.build_session_fn is None:
            raise Exception("SessionManager builder not initialized")

        if sessionid is None:
            sessionid = _rand_session_id()

        async with self._capacity_lock:
            active_count = len(self.sessions)
            if active_count >= self.max_session:
                raise MaxSessionError(
                    f"Maximum session limit reached ({active_count}/{self.max_session})"
                )
            if sessionid in self.sessions:
                raise MaxSessionError("Session ID is already reserved")
            logger.info(
                'Creating sessionid=%s, current session num=%d', sessionid, active_count
            )
            self.sessions[sessionid] = None

        build_future = asyncio.get_event_loop().run_in_executor(
            None, self.build_session_fn, sessionid, params
        )
        try:
            avatar_session = await asyncio.shield(build_future)
            async with self._capacity_lock:
                self.sessions[sessionid] = avatar_session
            return sessionid
        except asyncio.CancelledError:
            cleanup_task = asyncio.create_task(
                self._finish_cancelled_build(sessionid, build_future)
            )
            self._cleanup_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(self._cleanup_tasks.discard)
            raise
        except BaseException:
            async with self._capacity_lock:
                self.sessions.pop(sessionid, None)
            raise

    async def _finish_cancelled_build(self, sessionid: str, build_future) -> None:
        """Keep capacity reserved until an uncancellable executor build really finishes."""
        avatar_session = None
        try:
            avatar_session = await build_future
        except BaseException:
            logger.exception("Cancelled Avatar build did not complete successfully")
        else:
            tts = getattr(avatar_session, "tts", None)
            stop_tts = getattr(tts, "stop_tts", None)
            if callable(stop_tts):
                try:
                    stop_tts()
                except Exception:
                    logger.exception("Failed to stop unpublished Avatar TTS")
            output = getattr(avatar_session, "output", None)
            stop_output = getattr(output, "stop", None)
            if callable(stop_output):
                try:
                    stop_output()
                except Exception:
                    logger.exception("Failed to stop unpublished Avatar output")
        finally:
            async with self._capacity_lock:
                if self.sessions.get(sessionid) is None:
                    self.sessions.pop(sessionid, None)
'''
    session_manager.write_text(
        session_source[:method_start] + canonical_method + session_source[method_end:],
        encoding="utf-8",
    )


def apply_livetalking_compatibility_patches(
    repository: Path,
    *,
    standard_wav2lip_model: Path,
) -> None:
    if _sha256(standard_wav2lip_model) != WAV2LIP_MODEL_SOURCE_SHA256:
        raise RuntimeError("Standard Wav2Lip model source hash mismatch")
    model_source = standard_wav2lip_model.read_text(encoding="utf-8")
    normalized_model_source = "\n".join(line.rstrip() for line in model_source.splitlines()) + "\n"
    (repository / "avatars/wav2lip/models/wav2lip.py").write_text(
        normalized_model_source,
        encoding="utf-8",
    )
    _replace_required(
        repository / "avatars/wav2lip/models/__init__.py",
        "from .wav2lip_v2 import Wav2Lip, Wav2Lip_disc_qual",
        "from .wav2lip import Wav2Lip, Wav2Lip_disc_qual",
    )
    _replace_any_required(
        repository / "app.py",
        (
            'model = load_model("./models/wav2lip.pth")\n        global_avatars[opt.avatar_id] = load_avatar(opt.avatar_id)\n        warm_up(opt.batch_size,model,256)',
            'model = load_model("./models/wav2lip.pth")\n        global_avatars[opt.avatar_id] = load_avatar(opt.avatar_id)\n        warm_up(opt.batch_size,model,96)',
        ),
        'model = load_model(opt.modelfile or "./models/wav2lip256.pth", opt.modelres)\n        global_avatars[opt.avatar_id] = load_avatar(opt.avatar_id)\n        warm_up(opt.batch_size,model,opt.modelres)',
    )
    install_wav2lip_compositor(repository)
    install_wav2lip_inference_stride(repository)
    _replace_required(
        repository / "config.py",
        "    parser.add_argument('--modelres', type=int, default=192)",
        "    parser.add_argument('--modelres', type=int, default=192)\n"
        "    parser.add_argument('--wav2lip_inference_stride', type=int, choices=(1, 2), default=1)",
    )
    _replace_required(
        repository / "server/rtc_manager.py",
        """        ice_server = RTCIceServer(urls=self.opt.stun)
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[ice_server])
        )""",
        """        ice_servers = [RTCIceServer(urls=self.opt.stun)] if self.opt.stun else []
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=ice_servers)
        )""",
    )
    avatar = repository / "avatars/wav2lip_avatar.py"
    _replace_required(
        avatar,
        "from avatars.wav2lip.models import Wav2Lip",
        "from avatars.wav2lip.models.wav2lip import Wav2Lip as Wav2Lip96\n"
        "from avatars.wav2lip.models.wav2lip_v2 import Wav2Lip as Wav2Lip256",
    )
    _replace_required(avatar, "import pickle", "import json")
    _replace_required(
        avatar,
        """def _load(checkpoint_path):
    if device == 'cuda':
        checkpoint = torch.load(checkpoint_path)
    else:
        checkpoint = torch.load(checkpoint_path,
                                map_location=lambda storage, loc: storage)
    return checkpoint""",
        """def _load(checkpoint_path):
    return torch.load(checkpoint_path, map_location="cpu", weights_only=True)""",
    )
    _replace_required(
        avatar,
        """def load_model(path):
    model = Wav2Lip()""",
        """def load_model(path, modelres=256):
    if modelres not in (96, 256):
        raise ValueError("modelres must be 96 or 256")
    model = Wav2Lip256() if modelres == 256 else Wav2Lip96()""",
    )
    _replace_required(
        avatar,
        """    model = model.to(device)
    return model.eval()""",
        """    model = model.to(device)
    if modelres == 256 and str(device).startswith(("mps", "cuda")):
        model = model.half()
    return model.eval()""",
    )
    _replace_required(
        avatar,
        """    img_batch = torch.ones(batch_size, 6, modelres, modelres).to(device)
    mel_batch = torch.ones(batch_size, 1, 80, 16).to(device)""",
        """    dtype = next(model.parameters()).dtype
    img_batch = torch.ones(batch_size, 6, modelres, modelres, dtype=dtype).to(device)
    mel_batch = torch.ones(batch_size, 1, 80, 16, dtype=dtype).to(device)""",
    )
    _replace_required(
        avatar,
        """        img_batch = torch.FloatTensor(np.transpose(img_batch, (0, 3, 1, 2))).to(device)
        audiofeat_batch = torch.FloatTensor(np.transpose(audiofeat_batch, (0, 3, 1, 2))).to(device)""",
        """        dtype = next(self.model.parameters()).dtype
        img_batch = torch.as_tensor(np.transpose(img_batch, (0, 3, 1, 2)), dtype=dtype, device=device)
        audiofeat_batch = torch.as_tensor(np.transpose(audiofeat_batch, (0, 3, 1, 2)), dtype=dtype, device=device)""",
    )
    _replace_required(
        avatar,
        'coords_path = f"{avatar_path}/coords.pkl"',
        'coords_path = f"{avatar_path}/coords.json"',
    )
    _replace_required(
        avatar,
        "with open(coords_path, 'rb') as f:\n        coord_list_cycle = pickle.load(f)",
        "with open(coords_path, encoding='utf-8') as f:\n        coord_list_cycle = json.load(f)",
    )
    _replace_required(
        repository / "avatars/base_avatar.py",
        "            # Attribution is retained in documentation instead of burned into frames.",
        '            cv2.putText(combine_frame, "LiveTalking", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)',
    )
    generator = repository / "avatars/wav2lip/genavatar.py"
    _replace_required(generator, "import json, subprocess, random, string\n", "import json, subprocess, random, string, hashlib, re, shutil\n")
    _replace_required(generator, "import torch\nimport pickle\nfrom avatars.wav2lip import face_detection\n\n\ndevice = 'cuda' if torch.cuda.is_available() else 'cpu'\nprint('Using {} for inference.'.format(device))\n", "")
    _replace_required(
        generator,
        """    avatar_path = os.path.join(save_path, avatar_id)""",
        """    if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', avatar_id) is None:
        raise ValueError('invalid avatar_id')
    avatar_path = os.path.join(save_path, avatar_id)
    if os.path.exists(avatar_path):
        shutil.rmtree(avatar_path)""",
    )
    _replace_required(
        generator,
        """def video2imgs(vid_path, save_path, ext = '.png',cut_frame = 10000000):
    cap = cv2.VideoCapture(vid_path)
    count = 0
    while True:
        if count > cut_frame:
            break
        ret, frame = cap.read()
        if ret:
            cv2.putText(frame, \"LiveTalking\", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)
            cv2.imwrite(f\"{save_path}/{count:08d}.png\", frame)
            count += 1
        else:
            break""",
        """def video2imgs(vid_path, save_path, ext = '.png',cut_frame = 10000000, target_fps=25):
    cap = cv2.VideoCapture(vid_path)
    source_fps = cap.get(cv2.CAP_PROP_FPS) or target_fps
    source_frames = []
    while True:
        if len(source_frames) > cut_frame:
            break
        ret, frame = cap.read()
        if ret:
            source_frames.append(frame)
        else:
            break
    cap.release()
    if not source_frames:
        raise ValueError(\"Avatar source contains no readable frames\")
    target_count = max(1, round(len(source_frames) * target_fps / source_fps))
    for index in range(target_count):
        source_index = min(len(source_frames) - 1, int(index * source_fps / target_fps))
        cv2.imwrite(f\"{save_path}/{index:08d}.png\", source_frames[source_index])
    return target_count""",
    )
    _replace_required(generator, 'coords_path = os.path.join(avatar_path, "coords.pkl")', 'coords_path = os.path.join(avatar_path, "coords.json")')
    _replace_required(generator, "video2imgs(video_path, full_imgs_path, ext='png')", "frame_count = video2imgs(video_path, full_imgs_path, ext='png', target_fps=25)")
    _replace_required(
        generator,
        """    print('正在检测人脸...')
    detector = face_detection.FaceAlignment(face_detection.LandmarksType._2D,
                                            flip_input=False, device=device)

    batch_size = face_det_batch_size
    predictions = []

    while 1:
        predictions = []
        try:
            for i in range(0, len(frames), batch_size):
                predictions.extend(detector.get_detections_for_batch(np.array(frames[i:i + batch_size])))
                if progress_callback:
                    progress = 40 + int((i + batch_size) / len(frames) * 40)
                    progress_callback(min(progress, 80))
        except RuntimeError:
            if batch_size == 1:
                raise RuntimeError('Image too big to run face detection on GPU.')
            batch_size //= 2
            print('Recovering from OOM error; New batch size: {}'.format(batch_size))
            continue
        break""",
        """    print('正在使用本地 OpenCV 检测人脸...')
    detector = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
    )
    if detector.empty():
        raise RuntimeError('Bundled OpenCV face detector is unavailable')
    predictions = []
    previous = None
    for index, image in enumerate(frames):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        minimum = max(36, min(image.shape[:2]) // 10)
        faces = detector.detectMultiScale(
            gray, scaleFactor=1.08, minNeighbors=4, minSize=(minimum, minimum)
        )
        if len(faces):
            if previous is None:
                x, y, width, height = max(faces, key=lambda item: item[2] * item[3])
            else:
                center_x = (previous[0] + previous[2]) / 2
                center_y = (previous[1] + previous[3]) / 2
                x, y, width, height = min(
                    faces,
                    key=lambda item: ((item[0] + item[2] / 2) - center_x) ** 2
                    + ((item[1] + item[3] / 2) - center_y) ** 2,
                )
            previous = [int(x), int(y), int(x + width), int(y + height)]
        if previous is None:
            height, width = image.shape[:2]
            previous = [width // 4, height // 10, width * 3 // 4, height * 7 // 10]
        predictions.append(previous.copy())
        if progress_callback:
            progress_callback(40 + int((index + 1) / len(frames) * 40))""",
    )
    _replace_required(
        generator,
        """    with open(coords_path, 'wb') as f:
        pickle.dump(coord_list, f)""",
        """    with open(coords_path, 'w', encoding='utf-8') as f:
        json.dump(coord_list, f, separators=(',', ':'))
    with open(os.path.join(avatar_path, \"manifest.json\"), 'w', encoding='utf-8') as f:
        source_digest = hashlib.sha256()
        with open(video_path, 'rb') as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b''):
                source_digest.update(chunk)
        json.dump({
            \"schema_version\": 1,
            \"avatar_id\": avatar_id,
            \"source\": os.path.abspath(video_path),
            \"source_sha256\": source_digest.hexdigest(),
            \"frame_count\": frame_count,
            \"fps\": 25,
            \"face_size\": img_size,
            \"model\": \"wav2lip\",
            \"face_box_mode\": \"per_frame\",
            \"rights_confirmed\": True,
        }, f, ensure_ascii=False, indent=2)""",
    )
    _replace_required(generator, "    del detector\n", "")
    apply_livetalking_security_patches(repository)


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def _python_matches(python: Path, expected: str) -> bool:
    if not python.is_file():
        return False
    try:
        probe = subprocess.run(
            [str(python), "-c", "import platform; print(platform.python_version())"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0 and probe.stdout.strip() == expected


def _capture(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, check=True, text=True).stdout


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required executable is missing: {name}")
    return executable


def _verify_existing_checkout(git: str, repository: Path) -> None:
    origin = _capture([git, "-C", str(repository), "remote", "get-url", "origin"]).strip()
    commit = _capture([git, "-C", str(repository), "rev-parse", "HEAD"]).strip()
    if origin != LIVETALKING_REPOSITORY_URL or commit != LIVETALKING_COMMIT:
        raise RuntimeError("Existing LiveTalking checkout does not match the pinned source")
    diff = subprocess.run(
        [git, "-C", str(repository), "diff", "--binary", "HEAD"],
        capture_output=True,
        check=True,
    ).stdout
    if hashlib.sha256(diff).hexdigest() not in {
        hashlib.sha256(b"").hexdigest(),
        PREVIOUS_LIVETALKING_PATCH_DIFF_SHA256,
        LIVETALKING_PATCH_DIFF_SHA256,
    }:
        raise RuntimeError("Existing LiveTalking checkout has unexpected tracked changes")


def install_livetalking_runtime(plan: LiveTalkingSetupPlan) -> LiveTalkingRuntime:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This setup command is limited to Apple Silicon macOS")
    root = plan.runtime_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < plan.minimum_free_bytes:
        raise RuntimeError(
            f"LiveTalking setup requires at least {plan.minimum_free_bytes} free bytes"
        )

    wav2lip_root = root.parent / "wav2lip"
    standard_model = wav2lip_root / "repository/models/wav2lip.py"
    checkpoint = wav2lip_root / "repository/checkpoints/wav2lip.pth"
    checkpoint256 = wav2lip_root / "repository/checkpoints/wav2lip256.pth"
    if not standard_model.is_file() or not checkpoint.is_file() or not checkpoint256.is_file():
        raise RuntimeError("Install the verified Wav2Lip runtime before LiveTalking")
    if _sha256(checkpoint) != WAV2LIP_CHECKPOINT_SHA256:
        raise RuntimeError("Verified Wav2Lip checkpoint hash mismatch")
    if _sha256(checkpoint256) != WAV2LIP256_CHECKPOINT_SHA256:
        raise RuntimeError("Verified Wav2Lip 256 checkpoint hash mismatch")

    git = _required_executable("git")
    uv = _required_executable("uv")
    repository = root / "repository"
    environment = root / ".venv"
    python = environment / "bin/python"
    if repository.exists():
        if not (repository / ".git").is_dir():
            raise RuntimeError(f"Existing repository is not a Git checkout: {repository}")
        _verify_existing_checkout(git, repository)
    else:
        _run(
            [
                git,
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                plan.repository_url,
                str(repository),
            ]
        )
    _run([git, "-C", str(repository), "fetch", "--depth", "1", "origin", plan.commit])
    _run([git, "-C", str(repository), "checkout", "--detach", plan.commit])
    apply_livetalking_compatibility_patches(
        repository,
        standard_wav2lip_model=standard_model,
    )

    _run([uv, "python", "install", plan.python_version])
    if not _python_matches(python, plan.python_version):
        clear = ["--clear"] if environment.exists() else []
        _run([uv, "venv", *clear, "--python", plan.python_version, str(environment)])
    _run(
        [uv, "pip", "sync", "--python", str(python), str(plan.lock_file)],
        env={**os.environ, "UV_NO_CACHE": "1"},
    )
    model_link = repository / "models/wav2lip.pth"
    model_link.parent.mkdir(parents=True, exist_ok=True)
    if model_link.is_symlink() and model_link.resolve() != checkpoint.resolve():
        raise RuntimeError(f"Unexpected LiveTalking model symlink: {model_link}")
    if model_link.exists() and not model_link.is_symlink():
        raise RuntimeError(f"Refusing to replace existing LiveTalking model: {model_link}")
    if not model_link.exists():
        model_link.symlink_to(checkpoint.resolve())
    model256_link = repository / "models/wav2lip256.pth"
    if model256_link.is_symlink() and model256_link.resolve() != checkpoint256.resolve():
        raise RuntimeError(f"Unexpected LiveTalking model symlink: {model256_link}")
    if model256_link.exists() and not model256_link.is_symlink():
        raise RuntimeError(f"Refusing to replace existing LiveTalking model: {model256_link}")
    if not model256_link.exists():
        model256_link.symlink_to(checkpoint256.resolve())

    runtime = LiveTalkingRuntime(repository, python)
    diagnostic = inspect_livetalking_runtime(runtime)
    if not diagnostic.ready:
        raise RuntimeError("LiveTalking verification failed: " + "; ".join(diagnostic.issues))
    return runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/livetalking"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_livetalking_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        payload["lock_file"] = str(plan.lock_file)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    runtime = install_livetalking_runtime(plan)
    print(
        json.dumps(
            {"python": str(runtime.python), "repository": str(runtime.repository), "ready": True}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
