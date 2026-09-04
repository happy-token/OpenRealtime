#!/usr/bin/env python3
"""Generate the Phase 1 Voice Runtime release report from strict JSONL evidence.

Exit codes are suitable for CI release gates: 0=passed, 1=failed, 2=preview,
3=invalid evidence or report configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server.voice_session.quality import (
    ReleaseGateStatus,
    VoiceRuntimeQualityGate,
    load_turn_attempts_jsonl,
    quality_report_to_dict,
    render_quality_report_markdown,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="UTF-8 JSONL TurnAttempt evidence")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--minimum-attempted-turns", type=int, default=200)
    parser.add_argument(
        "--required-browser",
        action="append",
        dest="required_browsers",
        help="Required browser family; repeat as needed (default: chrome)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        attempts = load_turn_attempts_jsonl(args.evidence.read_text(encoding="utf-8"))
        gate_options: dict[str, object] = {"minimum_attempted_turns": args.minimum_attempted_turns}
        if args.required_browsers is not None:
            gate_options["required_browsers"] = tuple(args.required_browsers)
        report = VoiceRuntimeQualityGate(**gate_options).evaluate(attempts)
    except (OSError, TypeError, ValueError) as error:
        print(f"invalid Voice Runtime quality evidence: {error}", file=sys.stderr)
        return 3

    machine = (
        json.dumps(
            quality_report_to_dict(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    markdown = render_quality_report_markdown(report)
    try:
        if args.json_output is not None:
            _write_report(args.json_output, machine)
        if args.markdown_output is not None:
            _write_report(args.markdown_output, markdown)
    except OSError as error:
        print(f"could not write Voice Runtime quality report: {error}", file=sys.stderr)
        return 3
    if args.json_output is None and args.markdown_output is None:
        print(markdown, end="")

    return {
        ReleaseGateStatus.PASSED: 0,
        ReleaseGateStatus.FAILED: 1,
        ReleaseGateStatus.PREVIEW: 2,
    }[report.status]


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
