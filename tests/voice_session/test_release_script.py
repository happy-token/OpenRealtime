from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "test_voice_runtime.sh"


def test_voice_runtime_release_script_is_valid_and_has_no_deleted_test_paths() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    content = SCRIPT.read_text(encoding="utf-8")

    assert "tests/test_startup_smoke.py" not in content
    assert "tests/kernel" not in content
    assert "tests/conversation_engine" not in content
    assert "tests/scheduler" not in content


def test_voice_runtime_release_script_requires_chrome_only() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "Google Chrome.app" in content
    assert 'run_browser_e2e "chrome"' in content
    assert "Microsoft Edge.app" not in content
    assert 'run_browser_e2e "edge"' not in content


def test_voice_runtime_release_script_uses_an_isolated_e2e_port() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "allocate_e2e_port" in content
    assert 'PLAYWRIGHT_BASE_URL="http://127.0.0.1:${e2e_port}"' in content


def test_voice_runtime_release_script_requires_statistical_evidence() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "VOICE_RUNTIME_QUALITY_EVIDENCE" in content
    assert "generate_voice_runtime_quality_report.py" in content
    assert "test-results/voice-runtime-quality.json" in content
    assert "test-results/voice-runtime-quality.md" in content
