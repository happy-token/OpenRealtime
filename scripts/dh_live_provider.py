"""Verified launcher for the pinned DH_live_mini browser runtime."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.server
import json
import sys
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

DH_LIVE_REPOSITORY_URL = "https://github.com/kleinlee/DH_live.git"
DH_LIVE_COMMIT = "4467e97cd97194c2c54762043cf121c6d313db12"
PROBE_TIMEOUT_SECONDS = 30
ALLOWED_USAGE_SCOPES = {"internal_evaluation", "research"}
RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = 1
BLOCKED_DEMO_PATHS = frozenset({"/dialog.html", "/js/dialog.js", "/js/dialog_realtime.js"})
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "frame-src 'none'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'"
)
STATIC_FILES: dict[Path, tuple[int, str]] = {
    Path("web_demo/static/MiniLive.html"): (
        3_206,
        "e99f4774fa2526e31792c97c05c7c144a7c9fb9ed442746728d19cd9c581c11b",
    ),
    Path("web_demo/static/DHLiveMini.wasm"): (
        4_660_832,
        "7199459b6599a14190aa603d1859f9303fda004e4b78d3206907356d38094783",
    ),
    Path("web_demo/static/js/DHLiveMini.js"): (
        181_501,
        "d8d73e90011e87b40d49723f6d9bf2d8bbef7bb95dc6e2f40c6279d71bab5a9a",
    ),
    Path("web_demo/static/js/MiniLive2.js"): (
        28_495,
        "6c25c5b1a0c29b4dd86b066344ac04610eef12f238db0fa5bc6875d93fcb279f",
    ),
    Path("web_demo/static/js/MiniMateLoader.js"): (
        7_738,
        "64a61014b71662cfe535d6f72bd68657e189d812e3fb50b988343cdce9e86bca",
    ),
    Path("web_demo/static/js/pako.min.js"): (
        46_858,
        "59020f613e4f7d3bf11e8f6ac30ecaa15e2079f4fab1574487f029039d1da9d0",
    ),
    Path("web_demo/static/assets/01.mp4"): (
        834_555,
        "b70c76468c3383a4e9f2afeed1f73568de52dad17c02d9cbaa64608c05d77934",
    ),
    Path("web_demo/static/assets/combined_data.json.gz"): (
        132_623,
        "6c12fbd0ac5bf9f7f5f43100bb7caa5f4cfb5e37c86232f2f977b5397588561d",
    ),
    Path("web_demo/static/background/bg.mp4"): (
        1_812_946,
        "b542a4a9a72f5ec7c58a71bc698f73a3e53bb908722b86b4a29b1b7a3da215e0",
    ),
    Path("web_demo/static/common/bs_texture_halfFace.png"): (
        3_703,
        "37c5b168b3b2745219cc8bd158f6052f7ae8dd1013dc9f9e5e86649d7b03a8fb",
    ),
    Path("web_demo/static/dialog.html"): (
        3_939,
        "7ba9e3100808fbff7d708f148ef43c4b59278d4b0b6e33d2a23fd079b33b12a6",
    ),
    Path("web_demo/static/js/dialog.js"): (
        16_464,
        "43159293d788a163b719957f73d580a5d74a16e71d8df155b3c8d79792283322",
    ),
}
ALLOWED_DEMO_PATHS = frozenset(
    "/" + relative.relative_to("web_demo/static").as_posix()
    for relative in STATIC_FILES
    if "/" + relative.relative_to("web_demo/static").as_posix() not in BLOCKED_DEMO_PATHS
)


@dataclass(frozen=True)
class DHLiveRuntime:
    repository: Path
    python: Path


@dataclass(frozen=True)
class DHLiveDiagnostic:
    ready: bool
    device: str
    sample_frames: int | None
    license_status: str
    issues: tuple[str, ...]


def validate_dh_live_serve_options(
    runtime: DHLiveRuntime,
    *,
    port: int = 8890,
    usage_scope: str = "internal_evaluation",
) -> Path:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if type(usage_scope) is not str or usage_scope not in ALLOWED_USAGE_SCOPES:
        raise ValueError("DH_live requires license and avatar authorization review for promotion")
    return (runtime.repository / "web_demo/static").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_dh_live_assets(repository: Path) -> list[str]:
    issues: list[str] = []
    if not repository.is_dir():
        return [f"missing DH_live repository: {repository}"]
    if repository.is_symlink():
        return [f"DH_live repository cannot be a symbolic link: {repository}"]
    for relative, (expected_size, expected_hash) in STATIC_FILES.items():
        asset = repository / relative
        current = repository
        symlink_found = False
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                issues.append(f"symbolic link in browser runtime asset path: {relative}")
                symlink_found = True
                break
        if symlink_found:
            continue
        if not asset.is_file():
            issues.append(f"missing browser runtime asset: {relative}")
        elif asset.stat().st_size != expected_size or _sha256(asset) != expected_hash:
            issues.append(f"invalid browser runtime asset: {relative}")
    return issues


def _inspect_runtime_manifest(runtime: DHLiveRuntime) -> list[str]:
    manifest = runtime.repository.parent / RUNTIME_MANIFEST_NAME
    if not manifest.is_file() or manifest.is_symlink():
        return [f"missing DH_live runtime manifest: {manifest}"]
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["invalid DH_live runtime manifest"]
    expected = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "repository_url": DH_LIVE_REPOSITORY_URL,
        "commit": DH_LIVE_COMMIT,
    }
    if type(payload) is not dict or payload != expected:
        return ["invalid DH_live runtime manifest"]
    return []


def inspect_dh_live_runtime(runtime: DHLiveRuntime) -> DHLiveDiagnostic:
    issues: list[str] = []
    if not runtime.python.is_file():
        issues.append(f"missing Python executable: {runtime.python}")
    issues.extend(inspect_dh_live_assets(runtime.repository))
    issues.extend(_inspect_runtime_manifest(runtime))

    sample_frames: int | None = None
    sample_manifest = runtime.repository / "web_demo/static/assets/combined_data.json.gz"
    if sample_manifest.is_file() and not any("combined_data.json.gz" in issue for issue in issues):
        try:
            with gzip.open(sample_manifest, "rt", encoding="utf-8") as source:
                payload = json.load(source)
            if (
                type(payload) is not dict
                or payload.get("version") != 1
                or type(payload.get("frame_num")) is not int
                or payload["frame_num"] <= 0
                or payload.get("authorized") is not False
            ):
                raise ValueError
            sample_frames = payload["frame_num"]
        except (OSError, EOFError, json.JSONDecodeError, TypeError, ValueError):
            issues.append("invalid DH_live sample avatar manifest")

    return DHLiveDiagnostic(
        ready=not issues,
        device="browser-cpu-webgl",
        sample_frames=sample_frames,
        license_status="readme-mit-claim-root-license-missing-avatar-auth-required",
        issues=tuple(issues),
    )


class SafeDHLiveRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve only the renderer sample and add browser isolation headers."""

    def _blocked(self) -> bool:
        return urlsplit(self.path).path not in ALLOWED_DEMO_PATHS

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


def serve_dh_live(runtime: DHLiveRuntime, *, port: int, usage_scope: str) -> None:
    server = create_dh_live_server(runtime, port=port, usage_scope=usage_scope)
    with server:
        server.serve_forever()


def create_dh_live_server(
    runtime: DHLiveRuntime,
    *,
    port: int,
    usage_scope: str,
    allow_ephemeral: bool = False,
) -> http.server.ThreadingHTTPServer:
    validation_port = 1 if port == 0 and allow_ephemeral else port
    static_root = validate_dh_live_serve_options(
        runtime,
        port=validation_port,
        usage_scope=usage_scope,
    )
    handler = partial(SafeDHLiveRequestHandler, directory=str(static_root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("diagnose", "serve"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/dh_live"))
    parser.add_argument("--port", type=int, default=8890)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    runtime_root = args.runtime_root.resolve()
    runtime = DHLiveRuntime(runtime_root / "repository", Path(sys.executable).resolve())
    diagnostic = inspect_dh_live_runtime(runtime)
    if args.command == "diagnose":
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    if not diagnostic.ready:
        raise RuntimeError("DH_live runtime is not ready: " + "; ".join(diagnostic.issues))
    try:
        serve_dh_live(runtime, port=args.port, usage_scope="internal_evaluation")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
