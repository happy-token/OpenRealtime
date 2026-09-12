"""Block new mypy diagnostics while retaining an explicit, reviewed legacy baseline."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config/mypy-baseline.json"
DIAGNOSTIC = re.compile(r"^(.*?):\d+(?::\d+)?: error: (.*)$")


def diagnostics(output: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for line in output.splitlines():
        match = DIAGNOSTIC.match(line)
        if match:
            # In-message source line references move during unrelated edits too.
            message = re.sub(r"on line \d+", "on line <n>", match[2])
            result[f"{match[1]}: {message}"] += 1
    return result


def main() -> int:
    process = subprocess.run(
        [sys.executable, "-m", "mypy", "server", "--no-error-summary", "--no-pretty"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    current = diagnostics(process.stdout)
    if process.returncode not in (0, 1) or (process.returncode == 1 and not current):
        print(process.stdout + process.stderr, file=sys.stderr)
        return process.returncode or 1
    baseline = Counter(json.loads(BASELINE.read_text()))
    new = current - baseline
    if new:
        print("New mypy errors (baseline must not be expanded to bypass this gate):")
        for diagnostic, count in sorted(new.items()):
            print(f"{count}x {diagnostic}")
        return 1
    print(f"Mypy gate passed: {sum(current.values())} legacy diagnostics; no new errors.")
    removed = baseline - current
    if removed:
        print(f"{sum(removed.values())} baseline diagnostics no longer occur; shrink the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
