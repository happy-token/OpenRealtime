from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.collect_voice_runtime_quality_evidence import main as collect_evidence
from scripts.generate_voice_runtime_quality_report import main as generate_report
from server.voice_session.quality import (
    EvidenceKind,
    QualityCampaign,
    ReleaseGateStatus,
    TurnAttempt,
    VoiceRuntimeQualityGate,
    collect_turn_attempts_from_session_details,
    load_turn_attempts_jsonl,
    quality_report_to_dict,
    render_quality_report_markdown,
)


def attempt(
    index: int,
    *,
    browser: str | None = None,
    provider: str = "doubao-deepseek",
    evidence: EvidenceKind = EvidenceKind.LIVE,
    result_type: str = "ordinary",
) -> TurnAttempt:
    return TurnAttempt(
        attempt_id=f"attempt-{index}",
        engine="cascaded",
        provider=provider,
        capture_profile="phase1-v1",
        browser=browser or ("chrome" if index % 2 == 0 else "edge"),
        browser_version="128",
        network="normal",
        result_type=result_type,
        evidence=evidence,
        eot_to_playback_started_ms=700,
        barge_in_to_audio_stopped_ms=100,
        reconnect_to_active_ms=700,
        abnormal_terminal=False,
        voiced_sample_silent_loss=False,
    )


def attempt_payload(index: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "attempt_id": f"attempt-{index}",
        "engine": "cascaded",
        "provider": "doubao-deepseek",
        "capture_profile": "phase1-v1",
        "browser": "chrome" if index % 2 == 0 else "edge",
        "browser_version": "128",
        "network": "normal",
        "result_type": "ordinary",
        "evidence": "live",
        "eot_to_playback_started_ms": 700,
        "barge_in_to_audio_stopped_ms": 100,
        "reconnect_to_active_ms": 700,
        "abnormal_terminal": False,
        "voiced_sample_silent_loss": False,
        "correctness_violations": [],
    }
    payload.update(overrides)
    return payload


def test_quality_gate_requires_200_attempts_and_zero_correctness_violations() -> None:
    gate = VoiceRuntimeQualityGate(minimum_attempted_turns=200)

    preview = gate.evaluate(tuple(attempt(index) for index in range(199)))
    passed = gate.evaluate(tuple(attempt(index) for index in range(200)))
    violated = gate.evaluate(
        tuple(attempt(index) for index in range(199))
        + (replace(attempt(199), voiced_sample_silent_loss=True),)
    )

    assert preview.status is ReleaseGateStatus.PREVIEW
    assert passed.status is ReleaseGateStatus.PASSED
    assert violated.status is ReleaseGateStatus.FAILED


def test_default_release_gate_accepts_chrome_live_evidence_but_not_synthetic() -> None:
    gate = VoiceRuntimeQualityGate(minimum_attempted_turns=200)

    synthetic = gate.evaluate(
        tuple(attempt(index, evidence=EvidenceKind.SYNTHETIC) for index in range(200))
    )
    chrome_only = gate.evaluate(tuple(attempt(index, browser="chrome") for index in range(200)))

    assert synthetic.status is ReleaseGateStatus.PREVIEW
    assert synthetic.live_attempted_turns == 0
    assert chrome_only.status is ReleaseGateStatus.PASSED
    assert chrome_only.profiles[0].missing_required_browsers == ()


def test_minimum_attempts_apply_to_every_live_engine_provider_profile() -> None:
    gate = VoiceRuntimeQualityGate(minimum_attempted_turns=200)
    attempts = tuple(attempt(index) for index in range(200)) + (
        replace(
            attempt(200, provider="bella-deepseek"),
            attempt_id="other-profile-0",
        ),
    )

    report = gate.evaluate(attempts)

    assert report.status is ReleaseGateStatus.PREVIEW
    assert [profile.live_attempted_turns for profile in report.profiles] == [1, 200]
    assert report.profiles[0].sample_coverage_passed is False
    assert report.profiles[1].sample_coverage_passed is True


def test_reports_are_grouped_by_browser_version_network_and_result_type() -> None:
    gate = VoiceRuntimeQualityGate(minimum_attempted_turns=1, required_browsers=())

    report = gate.evaluate(
        (
            attempt(0, browser="chrome", result_type="ordinary"),
            replace(
                attempt(1, browser="chrome", result_type="barge_in"),
                browser_version="129",
                network="weak-4g",
            ),
        )
    )

    assert report.status is ReleaseGateStatus.PASSED
    assert len(report.groups) == 2
    assert {group.key.result_type for group in report.groups} == {
        "barge_in",
        "ordinary",
    }
    assert {group.key.browser_version for group in report.groups} == {"128", "129"}


def test_collector_builds_content_free_attempts_from_runtime_diagnostics() -> None:
    campaign = QualityCampaign(
        run_id="run-1",
        engine="cascaded",
        provider="doubao-asr+deepseek+doubao-tts",
        capture_profile="desktop-web-phase1-v1",
        browser="chrome",
        browser_version="128.0",
        network="cn-normal",
        result_type="reconnect",
        evidence=EvidenceKind.LIVE,
    )
    detail = {
        "summary": {"voice_session_id": "voice-1"},
        "events": [
            {
                "name": "client.input_epoch_started",
                "generation": 1,
                "kind": "event",
                "outcome": "ok",
                "duration_ms": None,
                "attributes": {"effective_profile": {"profile_version": 1}},
            },
            {
                "name": "provider.doubao.asr",
                "generation": 1,
                "kind": "provider_call",
                "outcome": "ok",
                "duration_ms": 50,
                "attributes": {"provider": "doubao"},
            },
            {
                "name": "turn.endpoint_to_client_playback",
                "generation": 1,
                "kind": "span",
                "outcome": "ok",
                "duration_ms": 720,
                "attributes": {},
            },
            {
                "name": "client.transport_disconnect",
                "generation": 1,
                "kind": "span",
                "outcome": "ok",
                "duration_ms": 640,
                "attributes": {},
            },
            {
                "name": "turn.total",
                "generation": 1,
                "kind": "terminal",
                "outcome": "ok",
                "duration_ms": 900,
                "attributes": {},
            },
        ],
    }

    attempts = collect_turn_attempts_from_session_details((detail,), campaign)

    assert attempts == (
        TurnAttempt(
            attempt_id="run-1:voice-1:1",
            engine="cascaded",
            provider="doubao-asr+deepseek+doubao-tts",
            capture_profile="desktop-web-phase1-v1",
            browser="chrome",
            browser_version="128.0",
            network="cn-normal",
            result_type="reconnect",
            evidence=EvidenceKind.LIVE,
            eot_to_playback_started_ms=720,
            barge_in_to_audio_stopped_ms=None,
            reconnect_to_active_ms=640,
            abnormal_terminal=False,
            voiced_sample_silent_loss=False,
        ),
    )


def test_live_collector_rejects_sessions_without_provider_or_capture_evidence() -> None:
    campaign = QualityCampaign(
        run_id="run-1",
        engine="cascaded",
        provider="real-provider",
        capture_profile="phase1-v1",
        browser="chrome",
        browser_version="128",
        network="normal",
        result_type="ordinary",
        evidence=EvidenceKind.LIVE,
    )
    detail = {
        "summary": {"voice_session_id": "voice-1"},
        "events": [{
            "name": "turn.total",
            "generation": 1,
            "kind": "terminal",
            "outcome": "ok",
            "duration_ms": 100,
            "attributes": {},
        }],
    }

    with pytest.raises(ValueError, match="capture epoch"):
        collect_turn_attempts_from_session_details((detail,), campaign)


def test_collector_rejects_correctness_violations_without_a_stable_code() -> None:
    campaign = QualityCampaign(
        run_id="run-1",
        engine="cascaded",
        provider="fake",
        capture_profile="phase1-v1",
        browser="chrome",
        browser_version="128",
        network="local",
        result_type="ordinary",
        evidence=EvidenceKind.SYNTHETIC,
    )
    detail = {
        "summary": {"voice_session_id": "voice-1"},
        "events": [
            {
                "name": "client.input_epoch_started",
                "generation": 1,
                "kind": "event",
                "outcome": "ok",
                "duration_ms": None,
                "attributes": {},
            },
            {
                "name": "client.correctness_violation",
                "generation": 1,
                "kind": "event",
                "outcome": "error",
                "duration_ms": None,
                "attributes": {},
            },
            {
                "name": "turn.total",
                "generation": 1,
                "kind": "terminal",
                "outcome": "ok",
                "duration_ms": 100,
                "attributes": {},
            },
        ],
    }

    with pytest.raises(ValueError, match="stable non-empty code"):
        collect_turn_attempts_from_session_details((detail,), campaign)


def test_collector_cli_writes_jsonl_and_invocation_manifest(tmp_path) -> None:
    details = tmp_path / "details.json"
    evidence = tmp_path / "attempts.jsonl"
    detail = {
        "summary": {"voice_session_id": "voice-1"},
        "events": [
            {
                "name": "client.input_epoch_started",
                "generation": 1,
                "kind": "event",
                "outcome": "ok",
                "duration_ms": None,
                "attributes": {},
            },
            {
                "name": "turn.endpoint_to_client_playback",
                "generation": 1,
                "kind": "span",
                "outcome": "ok",
                "duration_ms": 700,
                "attributes": {},
            },
            {
                "name": "turn.total",
                "generation": 1,
                "kind": "terminal",
                "outcome": "ok",
                "duration_ms": 900,
                "attributes": {},
            },
        ],
    }
    details.write_text(json.dumps([detail]), encoding="utf-8")

    status = collect_evidence(
        [
            "--details-json",
            str(details),
            "--run-id",
            "synthetic-1",
            "--engine",
            "cascaded",
            "--provider",
            "fake",
            "--capture-profile",
            "phase1-v1",
            "--browser",
            "chrome",
            "--browser-version",
            "128",
            "--network",
            "local",
            "--result-type",
            "ordinary",
            "--output",
            str(evidence),
        ]
    )

    assert status == 0
    attempts = load_turn_attempts_jsonl(evidence.read_text(encoding="utf-8"))
    assert len(attempts) == 1
    assert attempts[0].evidence is EvidenceKind.SYNTHETIC
    manifest = json.loads(
        evidence.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["session_ids"] == ["voice-1"]
    assert manifest["batches"][0]["session_ids"] == ["voice-1"]
    assert manifest["content_policy"].startswith("No PCM")


def test_collector_append_preserves_manifest_session_batches(tmp_path) -> None:
    evidence = tmp_path / "attempts.jsonl"

    def collect(session_id: str, *, append: bool) -> int:
        details = tmp_path / f"{session_id}.json"
        details.write_text(
            json.dumps(
                [
                    {
                        "summary": {"voice_session_id": session_id},
                        "events": [
                            {
                                "name": "client.input_epoch_started",
                                "generation": 1,
                                "kind": "event",
                                "outcome": "ok",
                                "duration_ms": None,
                                "attributes": {},
                            },
                            {
                                "name": "turn.total",
                                "generation": 1,
                                "kind": "terminal",
                                "outcome": "ok",
                                "duration_ms": 100,
                                "attributes": {},
                            },
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        arguments = [
            "--details-json",
            str(details),
            "--run-id",
            "synthetic-1",
            "--engine",
            "cascaded",
            "--provider",
            "fake",
            "--capture-profile",
            "phase1-v1",
            "--browser",
            "chrome",
            "--browser-version",
            "128",
            "--network",
            "local",
            "--result-type",
            "ordinary",
            "--output",
            str(evidence),
        ]
        if append:
            arguments.append("--append")
        return collect_evidence(arguments)

    assert collect("voice-1", append=False) == 0
    assert collect("voice-2", append=True) == 0

    manifest = json.loads(
        evidence.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["session_ids"] == ["voice-1", "voice-2"]
    assert [batch["session_ids"] for batch in manifest["batches"]] == [
        ["voice-1"],
        ["voice-2"],
    ]
    assert manifest["total_output_attempts"] == 2


def test_duplicate_attempt_ids_and_non_finite_durations_are_rejected() -> None:
    gate = VoiceRuntimeQualityGate(minimum_attempted_turns=1, required_browsers=())

    with pytest.raises(ValueError, match="duplicate attempt_id"):
        gate.evaluate((attempt(0), attempt(0)))

    with pytest.raises(ValueError, match="finite"):
        replace(attempt(0), eot_to_playback_started_ms=float("nan"))


def test_jsonl_evidence_generates_machine_and_human_readable_reports() -> None:
    payloads = [attempt_payload(index) for index in range(2)]
    attempts = load_turn_attempts_jsonl("\n".join(json.dumps(payload) for payload in payloads))
    report = VoiceRuntimeQualityGate(minimum_attempted_turns=2).evaluate(attempts)

    machine = quality_report_to_dict(report)
    markdown = render_quality_report_markdown(report)

    assert machine["status"] == "passed"
    assert machine["live_attempted_turns"] == 2
    assert machine["minimum_attempted_turns_per_profile"] == 2
    assert machine["required_browsers"] == ["chrome"]
    assert machine["slo_thresholds"]["eot_to_playback_p95_ms"] == 1500
    assert machine["slo_thresholds"]["abnormal_terminal_rate"] == 0.005
    assert machine["profiles"][0]["sample_coverage_passed"] is True
    assert "# Voice Runtime Quality Report" in markdown
    assert "doubao-deepseek" in markdown
    assert "Minimum live attempts per Profile: 2" in markdown
    assert "PASSED" in markdown


def test_report_cli_writes_both_formats_and_returns_gate_status(tmp_path) -> None:
    evidence = tmp_path / "attempts.jsonl"
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"
    evidence.write_text(
        "\n".join(json.dumps(attempt_payload(index)) for index in range(2)),
        encoding="utf-8",
    )

    passed = generate_report(
        [
            str(evidence),
            "--json-output",
            str(report_json),
            "--markdown-output",
            str(report_markdown),
            "--minimum-attempted-turns",
            "2",
        ]
    )

    assert passed == 0
    assert json.loads(report_json.read_text(encoding="utf-8"))["status"] == "passed"
    assert "Status: **PASSED**" in report_markdown.read_text(encoding="utf-8")

    evidence.write_text(
        json.dumps(attempt_payload(0, evidence="synthetic")),
        encoding="utf-8",
    )
    assert generate_report([str(evidence), "--minimum-attempted-turns", "1"]) == 2

    evidence.write_text(
        json.dumps(attempt_payload(0, correctness_violations=["cross_session_audio"])),
        encoding="utf-8",
    )
    assert (
        generate_report(
            [
                str(evidence),
                "--minimum-attempted-turns",
                "1",
                "--required-browser",
                "chrome",
            ]
        )
        == 1
    )
