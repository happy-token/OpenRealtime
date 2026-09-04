#!/usr/bin/env python3
"""Collect strict, content-free Voice Runtime JSONL from diagnostics timelines."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from server.voice_session.quality import (
    EvidenceKind,
    QualityCampaign,
    collect_turn_attempts_from_session_details,
    load_turn_attempts_jsonl,
    turn_attempts_to_jsonl,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--control-plane-url")
    source.add_argument("--details-json", type=Path)
    parser.add_argument("--session-id", action="append", default=[])
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--capture-profile", required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--browser-version", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--result-type", required=True)
    parser.add_argument(
        "--evidence",
        choices=tuple(kind.value for kind in EvidenceKind),
        default=EvidenceKind.SYNTHETIC.value,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--append", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        campaign = QualityCampaign(
            run_id=args.run_id,
            engine=args.engine,
            provider=args.provider,
            capture_profile=args.capture_profile,
            browser=args.browser,
            browser_version=args.browser_version,
            network=args.network,
            result_type=args.result_type,
            evidence=EvidenceKind(args.evidence),
        )
        details = _load_details(args)
        collected = collect_turn_attempts_from_session_details(details, campaign)
        existing = ()
        if args.append and args.output.exists():
            existing = load_turn_attempts_jsonl(args.output.read_text(encoding="utf-8"))
        attempts = existing + collected
        attempt_ids = [attempt.attempt_id for attempt in attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("append would create duplicate attempt_id values")
        _write_atomic(args.output, turn_attempts_to_jsonl(attempts))
        manifest_path = args.manifest_output or args.output.with_suffix(
            args.output.suffix + ".manifest.json"
        )
        collected_at = datetime.now(UTC).isoformat()
        source = (
            str(args.details_json)
            if args.details_json is not None
            else args.control_plane_url
        )
        session_ids = [detail["summary"]["voice_session_id"] for detail in details]
        campaign_manifest = {
            "run_id": campaign.run_id,
            "engine": campaign.engine,
            "provider": campaign.provider,
            "capture_profile": campaign.capture_profile,
            "browser": campaign.browser,
            "browser_version": campaign.browser_version,
            "network": campaign.network,
            "result_type": campaign.result_type,
            "evidence": campaign.evidence.value,
        }
        previous_manifest = _load_previous_manifest(manifest_path) if args.append else None
        batches = _previous_batches(previous_manifest)
        batches.append(
            {
                "collected_at": collected_at,
                "source": source,
                "session_ids": session_ids,
                "collected_attempts": len(collected),
                "campaign": campaign_manifest,
            }
        )
        previous_session_ids = (
            previous_manifest.get("session_ids", [])
            if previous_manifest is not None
            else []
        )
        manifest = {
            "collected_at": collected_at,
            "source": source,
            "session_ids": list(dict.fromkeys(previous_session_ids + session_ids)),
            "campaign": campaign_manifest,
            "batches": batches,
            "collected_attempts": len(collected),
            "total_output_attempts": len(attempts),
            "content_policy": "No PCM, transcript, prompt, model token, credential, or tool secret.",
        }
        _write_atomic(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    except (HTTPError, OSError, TypeError, URLError, ValueError) as error:
        print(f"could not collect Voice Runtime quality evidence: {error}", file=sys.stderr)
        return 3
    print(f"collected {len(collected)} attempts into {args.output}")
    return 0


def _load_details(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    if args.details_json is not None:
        payload = json.loads(args.details_json.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise TypeError("details JSON must be an array of session detail objects")
        return tuple(payload)
    if not 1 <= args.minutes <= 525_600:
        raise ValueError("minutes must be between 1 and 525600")
    if not 1 <= args.limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    base = str(args.control_plane_url).rstrip("/")
    session_ids = tuple(dict.fromkeys(args.session_id))
    if not session_ids:
        query = urlencode({"minutes": args.minutes, "limit": args.limit})
        summaries = _get_json(f"{base}/observability/sessions?{query}")
        if not isinstance(summaries, list):
            raise ValueError("diagnostics sessions response must be an array")
        session_ids = tuple(
            summary["voice_session_id"]
            for summary in summaries
            if isinstance(summary, dict)
            and isinstance(summary.get("voice_session_id"), str)
        )
    return tuple(
        _require_detail(
            _get_json(f"{base}/observability/sessions/{quote(session_id, safe='')}")
        )
        for session_id in session_ids
    )


def _get_json(url: str) -> Any:
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def _require_detail(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("diagnostics session detail must be an object")
    return payload


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _load_previous_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("existing evidence manifest must be an object")
    session_ids = payload.get("session_ids", [])
    if not isinstance(session_ids, list) or not all(
        isinstance(session_id, str) for session_id in session_ids
    ):
        raise ValueError("existing evidence manifest session_ids must be strings")
    return payload


def _previous_batches(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    batches = manifest.get("batches")
    if batches is not None:
        if not isinstance(batches, list) or not all(
            isinstance(batch, dict) for batch in batches
        ):
            raise ValueError("existing evidence manifest batches must be objects")
        return list(batches)
    return [
        {
            "collected_at": manifest.get("collected_at"),
            "source": manifest.get("source"),
            "session_ids": manifest.get("session_ids", []),
            "collected_attempts": manifest.get("collected_attempts", 0),
            "campaign": manifest.get("campaign"),
        }
    ]


if __name__ == "__main__":
    raise SystemExit(main())
