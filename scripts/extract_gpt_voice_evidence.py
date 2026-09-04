#!/usr/bin/env python3
"""Build a reproducible GPT Voice evidence inventory from the local Codex app.

The extractor deliberately records metadata, hashes, relevant asset paths, and
protocol identifiers. It does not copy the proprietary application bundle into
the repository. Pass an already extracted ``app.asar`` directory to index the
small set of assets that contain Voice-specific identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import plistlib
from pathlib import Path
from typing import Any


IDENTIFIERS = (
    "/realtime/calls",
    "AudioWorkletNode",
    "RTCPeerConnection",
    "codex_delegation",
    "conversation.handoff.append",
    "conversation.item.create",
    "delegation.context.append",
    "end_realtime_voice_call",
    "input_audio_buffer.append",
    "item/tool/call",
    "oai-events",
    "realtime_delegation",
    "response.create",
    "send_realtime_voice_feedback",
    "session.context.append",
    "session.update",
    "speak_to_user",
    "thread/realtime/appendSpeech",
    "thread/realtime/appendText",
    "thread/realtime/listVoices",
    "thread/realtime/start",
    "thread/realtime/stop",
)

RESOURCE_NAMES = (
    "app.asar",
    "codex",
    "codex-code-mode-host",
    "codex-notification.wav",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    shown_path = str(path if root is None else path.relative_to(root))
    return {"path": shown_path, "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def find_identifiers(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        return [identifier for identifier in IDENTIFIERS if data.find(identifier.encode()) >= 0]


def extracted_assets(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name_match = "realtime" in path.name.lower() or "audio-worklet" in path.name.lower()
        size = path.stat().st_size
        identifiers = find_identifiers(path) if size <= 32 * 1024 * 1024 else []
        if not name_match and not identifiers:
            continue
        record = file_record(path, root=root)
        record["identifiers"] = identifiers
        records.append(record)
    return records


def build_inventory(app: Path, extracted_asar: Path | None) -> dict[str, Any]:
    contents = app / "Contents"
    resources = contents / "Resources"
    with (contents / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)

    resource_records = []
    identifier_locations: dict[str, list[str]] = {key: [] for key in IDENTIFIERS}
    for name in RESOURCE_NAMES:
        path = resources / name
        if not path.is_file():
            continue
        record = file_record(path)
        record["identifiers"] = find_identifiers(path)
        resource_records.append(record)
        for identifier in record["identifiers"]:
            identifier_locations[identifier].append(str(path))

    assets: list[dict[str, Any]] = []
    if extracted_asar is not None:
        assets = extracted_assets(extracted_asar)
        for record in assets:
            for identifier in record["identifiers"]:
                identifier_locations[identifier].append(f"app.asar:{record['path']}")

    return {
        "schema_version": 1,
        "scope": "Codex desktop Voice implementation; not the full consumer ChatGPT Voice source",
        "application": {
            "path": str(app),
            "bundle_id": info.get("CFBundleIdentifier"),
            "display_name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
            "short_version": info.get("CFBundleShortVersionString"),
            "build_version": info.get("CFBundleVersion"),
        },
        "resources": resource_records,
        "extracted_voice_assets": assets,
        "protocol_identifiers": {
            identifier: locations
            for identifier, locations in identifier_locations.items()
            if locations
        },
        "limitations": [
            "The renderer bundle is minified and ships without source maps.",
            "Cloud-side routing and model implementation are not present locally.",
            "Hashes identify the inspected build and will change after an app update.",
            "No proprietary bundle contents are copied by this extractor.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/ChatGPT.app"))
    parser.add_argument("--extracted-asar", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research/gpt-voice-local/evidence.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.app.is_dir():
        raise SystemExit(f"Application not found: {args.app}")
    if args.extracted_asar is not None and not args.extracted_asar.is_dir():
        raise SystemExit(f"Extracted app.asar directory not found: {args.extracted_asar}")
    inventory = build_inventory(args.app, args.extracted_asar)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
