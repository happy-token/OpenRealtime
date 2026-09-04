"""Validated loopback server for a custom DH_live_mini v1 browser avatar bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.server
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

DH_LIVE_V1_COMMIT = "8b74e3f73589339c0e5202ceea5b9a3afb4c3637"
AVATAR_MANIFEST_NAME = "avatar-manifest.json"
AVATAR_MANIFEST_SCHEMA = 1
ALLOWED_USAGE_SCOPES = {"internal_evaluation", "research"}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; connect-src 'self'; frame-ancestors 'none'; "
    "frame-src 'none'; img-src 'self' data: blob:; media-src 'self' blob:; "
    "object-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'"
)
RENDERER_FILES: dict[Path, tuple[int, str]] = {
    Path("MiniLive.html"): (
        2_802,
        "1382fd19e4400faf3a2972e93db50e146bc4e00bdcf8cf641704298af38c4ed5",
    ),
    Path("DHLiveMini.wasm"): (
        4_338_103,
        "261f30355597456719d98726d83ea78baf69ee29453b64ae3c7a1718944d8701",
    ),
    Path("js/DHLiveMini.js"): (
        180_592,
        "fb0563433bfdf64bf9c9abd27b8ef010f282cb962c06cf54e635fcf83977253e",
    ),
    Path("js/MiniLive2.js"): (
        23_234,
        "7d52b164e2899bb442f75a941fea3c8d4d352a45f5e92ad21a599686ad9bee3c",
    ),
    Path("js/MiniMateLoader.js"): (
        7_738,
        "64a61014b71662cfe535d6f72bd68657e189d812e3fb50b988343cdce9e86bca",
    ),
    Path("js/pako.min.js"): (
        46_858,
        "59020f613e4f7d3bf11e8f6ac30ecaa15e2079f4fab1574487f029039d1da9d0",
    ),
    Path("js/mp4box.all.min.js"): (
        155_452,
        "c44a2e2a331ebbb2c04f2816ce71db0767ef5b73c9374a431379371360be4589",
    ),
    Path("common/bs_texture_halfFace.png"): (
        3_703,
        "37c5b168b3b2745219cc8bd158f6052f7ae8dd1013dc9f9e5e86649d7b03a8fb",
    ),
}
AVATAR_FILES = (Path("assets/01.mp4"), Path("assets/combined_data.json.gz"))
ALLOWED_PATHS = frozenset("/" + path.as_posix() for path in (*RENDERER_FILES, *AVATAR_FILES))
MAX_AVATAR_VIDEO_BYTES = 256 * 1024 * 1024
MAX_AVATAR_DATA_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_AVATAR_DATA_BYTES = 256 * 1024 * 1024
MAX_AVATAR_MANIFEST_BYTES = 64 * 1024


@dataclass(frozen=True)
class DHLiveV1Diagnostic:
    ready: bool
    avatar_id: str | None
    frame_count: int | None
    canvas: str
    authorized: bool | None
    issues: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_regular_file(root: Path, relative: Path) -> Path | None:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def inspect_dh_live_v1_bundle(bundle: Path) -> DHLiveV1Diagnostic:
    issues: list[str] = []
    if not bundle.is_dir() or bundle.is_symlink():
        return DHLiveV1Diagnostic(False, None, None, "720x1280", None, ("invalid bundle",))
    for relative, (size, digest) in RENDERER_FILES.items():
        path = _safe_regular_file(bundle, relative)
        if path is None:
            issues.append(f"missing or unsafe renderer file: {relative}")
        elif path.stat().st_size != size or _sha256(path) != digest:
            issues.append(f"invalid renderer file: {relative}")

    manifest_path = _safe_regular_file(bundle, Path(AVATAR_MANIFEST_NAME))
    manifest: dict[str, object] = {}
    if manifest_path is None or manifest_path.stat().st_size > MAX_AVATAR_MANIFEST_BYTES:
        issues.append("missing avatar manifest")
    else:
        try:
            candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
            if type(candidate) is not dict:
                raise ValueError
            manifest = candidate
        except (OSError, json.JSONDecodeError, ValueError):
            issues.append("invalid avatar manifest")
    avatar_id = manifest.get("avatar_id") if isinstance(manifest.get("avatar_id"), str) else None
    if avatar_id is None or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", avatar_id):
        issues.append("invalid avatar id")
    if manifest.get("schema_version") != AVATAR_MANIFEST_SCHEMA:
        issues.append("unsupported avatar manifest schema")
    if manifest.get("runtime_commit") != DH_LIVE_V1_COMMIT:
        issues.append("avatar manifest runtime commit mismatch")
    if manifest.get("authorized") is not False:
        issues.append("avatar manifest authorization must remain false")
    if manifest.get("usage_scope") not in ALLOWED_USAGE_SCOPES:
        issues.append("avatar manifest usage scope is unsupported")
    source_video = manifest.get("source_video")
    if (
        type(source_video) is not dict
        or set(source_video) != {"size_bytes", "sha256"}
        or type(source_video.get("size_bytes")) is not int
        or not 0 < source_video["size_bytes"] <= MAX_AVATAR_VIDEO_BYTES
        or type(source_video.get("sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_video["sha256"]) is None
    ):
        issues.append("avatar manifest source video provenance is invalid")
    files = manifest.get("files")
    if type(files) is not dict or set(files) != {path.as_posix() for path in AVATAR_FILES}:
        issues.append("avatar manifest file set mismatch")
        files = {}
    for relative in AVATAR_FILES:
        path = _safe_regular_file(bundle, relative)
        entry = files.get(relative.as_posix()) if isinstance(files, dict) else None
        if path is None or type(entry) is not dict:
            issues.append(f"missing or unsafe avatar file: {relative}")
            continue
        if (
            type(entry.get("size_bytes")) is not int
            or type(entry.get("sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
            or path.stat().st_size != entry["size_bytes"]
            or _sha256(path) != entry["sha256"]
        ):
            issues.append(f"invalid avatar file: {relative}")
        elif (
            relative == Path("assets/01.mp4") and path.stat().st_size > MAX_AVATAR_VIDEO_BYTES
        ) or (
            relative == Path("assets/combined_data.json.gz")
            and path.stat().st_size > MAX_AVATAR_DATA_BYTES
        ):
            issues.append(f"avatar file exceeds the size boundary: {relative}")

    frame_count: int | None = None
    authorized: bool | None = None
    data_path = _safe_regular_file(bundle, Path("assets/combined_data.json.gz"))
    if data_path is not None and data_path.stat().st_size <= MAX_AVATAR_DATA_BYTES:
        try:
            with gzip.open(data_path, "rb") as source:
                raw_data = source.read(MAX_DECOMPRESSED_AVATAR_DATA_BYTES + 1)
            if len(raw_data) > MAX_DECOMPRESSED_AVATAR_DATA_BYTES:
                raise ValueError
            data = json.loads(raw_data)
            frame_count = data["frame_num"]
            authorized = data["authorized"]
            if (
                type(frame_count) is not int
                or not 25 <= frame_count <= 1_500
                or authorized is not False
                or type(data.get("uid")) is not str
                or not data["uid"].startswith("matesx_")
                or type(data.get("ref_data")) is not list
                or len(data["ref_data"]) != 6480
                or any(not _is_finite_number(value) for value in data["ref_data"])
                or type(data.get("json_data")) is not list
                or len(data["json_data"]) != frame_count
                or any(
                    type(frame) is not dict
                    or type(frame.get("rect")) is not list
                    or len(frame["rect"]) != 4
                    or any(not _is_finite_number(value) for value in frame["rect"])
                    or type(frame.get("points")) is not list
                    or len(frame["points"]) != 434
                    or any(not _is_finite_number(value) for value in frame["points"])
                    for frame in data["json_data"]
                )
            ):
                raise ValueError
        except (OSError, EOFError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            issues.append("invalid avatar data")

    video_path = _safe_regular_file(bundle, Path("assets/01.mp4"))
    if (
        video_path is not None
        and video_path.stat().st_size <= MAX_AVATAR_VIDEO_BYTES
        and frame_count is not None
    ):
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-count_frames",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate,nb_read_frames",
                    "-of",
                    "json",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stream = json.loads(probe.stdout)["streams"][0]
            numerator, denominator = (float(value) for value in stream["r_frame_rate"].split("/"))
            if denominator == 0:
                raise ValueError
            fps = numerator / denominator
            if (
                int(stream["width"]) != 720
                or int(stream["height"]) != 1280
                or not math.isclose(fps, 25, abs_tol=0.01)
                or int(stream["nb_read_frames"]) != frame_count
            ):
                raise ValueError
        except (OSError, subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError):
            issues.append("avatar video does not match the 720x1280 25fps manifest")

    return DHLiveV1Diagnostic(
        ready=not issues,
        avatar_id=avatar_id,
        frame_count=frame_count,
        canvas="720x1280",
        authorized=authorized,
        issues=tuple(issues),
    )


def _is_finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


class SafeDHLiveV1RequestHandler(http.server.SimpleHTTPRequestHandler):
    def _blocked(self) -> bool:
        return urlsplit(self.path).path not in ALLOWED_PATHS

    def do_GET(self) -> None:
        if self._blocked():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._blocked():
            self.send_error(404)
            return
        super().do_HEAD()

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()


def create_dh_live_v1_server(
    bundle: Path,
    *,
    port: int,
    usage_scope: str = "internal_evaluation",
    allow_ephemeral: bool = False,
) -> http.server.ThreadingHTTPServer:
    if usage_scope not in ALLOWED_USAGE_SCOPES:
        raise ValueError("DH_live avatar authorization is required for promotional use")
    if type(port) is not int or (not (port == 0 and allow_ephemeral) and not 1 <= port <= 65535):
        raise ValueError("port must be between 1 and 65535")
    diagnostic = inspect_dh_live_v1_bundle(bundle.resolve())
    if not diagnostic.ready:
        raise RuntimeError("DH_live v1 bundle is not ready: " + "; ".join(diagnostic.issues))
    handler = partial(SafeDHLiveV1RequestHandler, directory=str(bundle.resolve()))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("diagnose", "serve"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8892)
    args = parser.parse_args()
    diagnostic = inspect_dh_live_v1_bundle(args.bundle.resolve())
    if args.command == "diagnose":
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    server = create_dh_live_v1_server(args.bundle, port=args.port)
    try:
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
