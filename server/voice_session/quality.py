"""Deterministic Phase 1 correctness and statistical release gates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

EOT_TO_PLAYBACK_P50_MS_MAX_EXCLUSIVE = 800
EOT_TO_PLAYBACK_P95_MS_MAX_EXCLUSIVE = 1500
BARGE_IN_STOP_P95_MS_MAX_EXCLUSIVE = 200
RECONNECT_P95_MS_MAX_EXCLUSIVE = 1000
ABNORMAL_TERMINAL_RATE_MAX_EXCLUSIVE = 0.005


class ReleaseGateStatus(StrEnum):
    PREVIEW = "preview"
    PASSED = "passed"
    FAILED = "failed"


class EvidenceKind(StrEnum):
    """Whether an attempt observed a real provider/browser path or a test double."""

    LIVE = "live"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityCampaign:
    """Operator-owned dimensions applied to one browser campaign export."""

    run_id: str
    engine: str
    provider: str
    capture_profile: str
    browser: str
    browser_version: str
    network: str
    result_type: str
    evidence: EvidenceKind

    def __post_init__(self) -> None:
        values = (
            self.run_id,
            self.engine,
            self.provider,
            self.capture_profile,
            self.browser,
            self.browser_version,
            self.network,
            self.result_type,
        )
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("quality campaign dimensions must be non-empty strings")
        if not isinstance(self.evidence, EvidenceKind):
            raise TypeError("quality campaign evidence must be an EvidenceKind")


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnAttempt:
    attempt_id: str
    engine: str
    provider: str
    capture_profile: str
    browser: str
    browser_version: str
    network: str
    result_type: str
    evidence: EvidenceKind
    eot_to_playback_started_ms: float | None
    barge_in_to_audio_stopped_ms: float | None
    reconnect_to_active_ms: float | None
    abnormal_terminal: bool
    voiced_sample_silent_loss: bool
    correctness_violations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        dimensions = (
            self.attempt_id,
            self.engine,
            self.provider,
            self.capture_profile,
            self.browser,
            self.browser_version,
            self.network,
            self.result_type,
        )
        if any(not isinstance(value, str) for value in dimensions):
            raise TypeError("Voice Runtime quality dimensions must be strings")
        if not all(dimensions):
            raise ValueError("Voice Runtime quality dimensions must be non-empty")
        if not isinstance(self.evidence, EvidenceKind):
            raise TypeError("Voice Runtime evidence must be an EvidenceKind")
        if not isinstance(self.abnormal_terminal, bool):
            raise TypeError("abnormal_terminal must be a boolean")
        if not isinstance(self.voiced_sample_silent_loss, bool):
            raise TypeError("voiced_sample_silent_loss must be a boolean")
        if any(not isinstance(value, str) or not value for value in self.correctness_violations):
            raise ValueError("correctness violations must be non-empty strings")
        for duration in (
            self.eot_to_playback_started_ms,
            self.barge_in_to_audio_stopped_ms,
            self.reconnect_to_active_ms,
        ):
            if duration is not None and (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or not math.isfinite(duration)
            ):
                raise ValueError("Voice Runtime quality durations must be finite numbers")
            if duration is not None and duration < 0:
                raise ValueError("Voice Runtime quality durations must not be negative")


@dataclass(frozen=True, slots=True)
class QualityProfileKey:
    engine: str
    provider: str
    capture_profile: str


@dataclass(frozen=True, slots=True)
class QualityGroupKey:
    engine: str
    provider: str
    capture_profile: str
    browser: str
    browser_version: str
    network: str
    result_type: str
    evidence: EvidenceKind


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityProfileReport:
    key: QualityProfileKey
    live_attempted_turns: int
    observed_browsers: tuple[str, ...]
    missing_required_browsers: tuple[str, ...]
    sample_coverage_passed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityGroupReport:
    key: QualityGroupKey
    attempted_turns: int
    eot_to_playback_p50_ms: float | None
    eot_to_playback_p95_ms: float | None
    barge_in_stop_p95_ms: float | None
    reconnect_p95_ms: float | None
    abnormal_terminal_rate: float
    correctness_violation_count: int
    slo_passed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceRuntimeQualityReport:
    status: ReleaseGateStatus
    attempted_turns: int
    live_attempted_turns: int
    minimum_attempted_turns_per_profile: int
    required_browsers: tuple[str, ...]
    profiles: tuple[QualityProfileReport, ...]
    groups: tuple[QualityGroupReport, ...]


class VoiceRuntimeQualityGate:
    def __init__(
        self,
        *,
        minimum_attempted_turns: int = 200,
        required_browsers: tuple[str, ...] = ("chrome",),
    ) -> None:
        if minimum_attempted_turns < 1:
            raise ValueError("minimum attempted turns must be positive")
        if any(not browser.strip() for browser in required_browsers):
            raise ValueError("required browser names must be non-empty")
        self._minimum_attempted_turns = minimum_attempted_turns
        self._required_browsers = frozenset(
            browser.strip().lower() for browser in required_browsers
        )

    def evaluate(self, attempts: tuple[TurnAttempt, ...]) -> VoiceRuntimeQualityReport:
        attempt_ids = [attempt.attempt_id for attempt in attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("duplicate attempt_id in Voice Runtime quality evidence")
        grouped: dict[QualityGroupKey, list[TurnAttempt]] = {}
        for attempt in attempts:
            key = QualityGroupKey(
                engine=attempt.engine,
                provider=attempt.provider,
                capture_profile=attempt.capture_profile,
                browser=attempt.browser,
                browser_version=attempt.browser_version,
                network=attempt.network,
                result_type=attempt.result_type,
                evidence=attempt.evidence,
            )
            grouped.setdefault(key, []).append(attempt)
        reports = tuple(
            self._group_report(key, tuple(values))
            for key, values in sorted(grouped.items(), key=lambda entry: repr(entry[0]))
        )
        live_attempts = tuple(
            attempt for attempt in attempts if attempt.evidence is EvidenceKind.LIVE
        )
        profiles = self._profile_reports(live_attempts)
        correctness_failed = any(report.correctness_violation_count > 0 for report in reports)
        if correctness_failed:
            status = ReleaseGateStatus.FAILED
        elif not profiles or not all(profile.sample_coverage_passed for profile in profiles):
            status = ReleaseGateStatus.PREVIEW
        elif all(
            report.slo_passed for report in reports if report.key.evidence is EvidenceKind.LIVE
        ):
            status = ReleaseGateStatus.PASSED
        else:
            status = ReleaseGateStatus.FAILED
        return VoiceRuntimeQualityReport(
            status=status,
            attempted_turns=len(attempts),
            live_attempted_turns=len(live_attempts),
            minimum_attempted_turns_per_profile=self._minimum_attempted_turns,
            required_browsers=tuple(sorted(self._required_browsers)),
            profiles=profiles,
            groups=reports,
        )

    def _profile_reports(
        self, attempts: tuple[TurnAttempt, ...]
    ) -> tuple[QualityProfileReport, ...]:
        grouped: dict[QualityProfileKey, list[TurnAttempt]] = {}
        for attempt in attempts:
            key = QualityProfileKey(
                engine=attempt.engine,
                provider=attempt.provider,
                capture_profile=attempt.capture_profile,
            )
            grouped.setdefault(key, []).append(attempt)
        reports: list[QualityProfileReport] = []
        for key, values in sorted(grouped.items(), key=lambda entry: repr(entry[0])):
            observed = tuple(sorted({attempt.browser.lower() for attempt in values}))
            missing = tuple(sorted(self._required_browsers.difference(observed)))
            reports.append(
                QualityProfileReport(
                    key=key,
                    live_attempted_turns=len(values),
                    observed_browsers=observed,
                    missing_required_browsers=missing,
                    sample_coverage_passed=(
                        len(values) >= self._minimum_attempted_turns and not missing
                    ),
                )
            )
        return tuple(reports)

    @staticmethod
    def _group_report(
        key: QualityGroupKey, attempts: tuple[TurnAttempt, ...]
    ) -> QualityGroupReport:
        playback = _values(attempts, "eot_to_playback_started_ms")
        barge_in = _values(attempts, "barge_in_to_audio_stopped_ms")
        reconnect = _values(attempts, "reconnect_to_active_ms")
        abnormal_rate = sum(attempt.abnormal_terminal for attempt in attempts) / len(attempts)
        correctness_violations = sum(
            int(attempt.voiced_sample_silent_loss) + len(attempt.correctness_violations)
            for attempt in attempts
        )
        playback_p50 = _percentile(playback, 0.5)
        playback_p95 = _percentile(playback, 0.95)
        barge_p95 = _percentile(barge_in, 0.95)
        reconnect_p95 = _percentile(reconnect, 0.95)
        slo_passed = (
            playback_p50 is not None
            and playback_p50 < EOT_TO_PLAYBACK_P50_MS_MAX_EXCLUSIVE
            and playback_p95 is not None
            and playback_p95 < EOT_TO_PLAYBACK_P95_MS_MAX_EXCLUSIVE
            and (barge_p95 is None or barge_p95 < BARGE_IN_STOP_P95_MS_MAX_EXCLUSIVE)
            and (reconnect_p95 is None or reconnect_p95 < RECONNECT_P95_MS_MAX_EXCLUSIVE)
            and abnormal_rate < ABNORMAL_TERMINAL_RATE_MAX_EXCLUSIVE
            and correctness_violations == 0
        )
        return QualityGroupReport(
            key=key,
            attempted_turns=len(attempts),
            eot_to_playback_p50_ms=playback_p50,
            eot_to_playback_p95_ms=playback_p95,
            barge_in_stop_p95_ms=barge_p95,
            reconnect_p95_ms=reconnect_p95,
            abnormal_terminal_rate=abnormal_rate,
            correctness_violation_count=correctness_violations,
            slo_passed=slo_passed,
        )


def collect_turn_attempts_from_session_details(
    details: tuple[dict[str, Any], ...],
    campaign: QualityCampaign,
) -> tuple[TurnAttempt, ...]:
    """Project content-free diagnostics into strict per-turn release evidence."""

    attempts: list[TurnAttempt] = []
    for detail in details:
        summary = _required_mapping(detail, "summary")
        voice_session_id = summary.get("voice_session_id")
        if not isinstance(voice_session_id, str) or not voice_session_id:
            raise ValueError("quality diagnostics summary lacks voice_session_id")
        raw_events = detail.get("events")
        if not isinstance(raw_events, list):
            raise TypeError(f"quality diagnostics for {voice_session_id} lacks events")
        events = tuple(_event_mapping(event, voice_session_id) for event in raw_events)
        terminals: dict[int, dict[str, Any]] = {}
        for event in events:
            if event.get("name") != "turn.total":
                continue
            generation = event.get("generation")
            if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
                raise ValueError(f"turn.total in {voice_session_id} lacks generation")
            if generation in terminals:
                raise ValueError(
                    f"duplicate turn.total for {voice_session_id} generation {generation}"
                )
            terminals[generation] = event
        if not terminals:
            continue
        if not any(event.get("name") == "client.input_epoch_started" for event in events):
            raise ValueError(f"live voice session {voice_session_id} lacks capture epoch evidence")
        if campaign.evidence is EvidenceKind.LIVE and not any(
            event.get("kind") == "provider_call" for event in events
        ):
            raise ValueError(f"live voice session {voice_session_id} lacks provider evidence")

        for generation, terminal in sorted(terminals.items()):
            generation_events = tuple(
                event for event in events if event.get("generation") == generation
            )
            capture_failed = any(
                event.get("name") == "client.input_capture_failed"
                for event in generation_events
            )
            barge_in_ms = _maximum_duration(
                generation_events,
                "barge_in.time_to_client_stop",
            )
            outcome = terminal.get("outcome")
            expected_cancel = outcome == "cancelled" and barge_in_ms is not None
            violations = tuple(
                _correctness_violation_code(event)
                for event in generation_events
                if event.get("name") == "client.correctness_violation"
            )
            attempts.append(
                TurnAttempt(
                    attempt_id=f"{campaign.run_id}:{voice_session_id}:{generation}",
                    engine=campaign.engine,
                    provider=campaign.provider,
                    capture_profile=campaign.capture_profile,
                    browser=campaign.browser,
                    browser_version=campaign.browser_version,
                    network=campaign.network,
                    result_type=campaign.result_type,
                    evidence=campaign.evidence,
                    eot_to_playback_started_ms=_maximum_duration(
                        generation_events,
                        "turn.endpoint_to_client_playback",
                    ),
                    barge_in_to_audio_stopped_ms=barge_in_ms,
                    reconnect_to_active_ms=_maximum_duration(
                        generation_events,
                        "client.transport_disconnect",
                    ),
                    abnormal_terminal=(
                        capture_failed
                        or outcome not in {"ok", "superseded"}
                        and not expected_cancel
                    ),
                    voiced_sample_silent_loss=any(
                        event.get("name") == "client.voiced_sample_silent_loss"
                        for event in generation_events
                    ),
                    correctness_violations=violations,
                )
            )
    attempt_ids = [attempt.attempt_id for attempt in attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("duplicate attempt_id in collected Voice Runtime evidence")
    return tuple(attempts)


def turn_attempts_to_jsonl(attempts: tuple[TurnAttempt, ...]) -> str:
    return "".join(
        json.dumps(
            {
                "attempt_id": attempt.attempt_id,
                "engine": attempt.engine,
                "provider": attempt.provider,
                "capture_profile": attempt.capture_profile,
                "browser": attempt.browser,
                "browser_version": attempt.browser_version,
                "network": attempt.network,
                "result_type": attempt.result_type,
                "evidence": attempt.evidence.value,
                "eot_to_playback_started_ms": attempt.eot_to_playback_started_ms,
                "barge_in_to_audio_stopped_ms": attempt.barge_in_to_audio_stopped_ms,
                "reconnect_to_active_ms": attempt.reconnect_to_active_ms,
                "abnormal_terminal": attempt.abnormal_terminal,
                "voiced_sample_silent_loss": attempt.voiced_sample_silent_loss,
                "correctness_violations": list(attempt.correctness_violations),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for attempt in attempts
    )


def _required_mapping(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise TypeError(f"quality diagnostics field {field} must be an object")
    return value


def _event_mapping(event: Any, voice_session_id: str) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise TypeError(f"quality diagnostics for {voice_session_id} contains invalid event")
    if not isinstance(event.get("name"), str):
        raise TypeError(f"quality diagnostics for {voice_session_id} contains unnamed event")
    return event


def _correctness_violation_code(event: dict[str, Any]) -> str:
    code = _required_mapping(event, "attributes").get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("correctness violation requires a stable non-empty code")
    return code


def _maximum_duration(events: tuple[dict[str, Any], ...], name: str) -> float | None:
    values = []
    for event in events:
        if event.get("name") != name:
            continue
        duration = event.get("duration_ms")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            raise TypeError(f"quality metric {name} lacks numeric duration_ms")
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(f"quality metric {name} has invalid duration_ms")
        values.append(float(duration))
    return max(values) if values else None


def _values(attempts: tuple[TurnAttempt, ...], field: str) -> tuple[float, ...]:
    return tuple(value for attempt in attempts if (value := getattr(attempt, field)) is not None)


def _percentile(values: tuple[float, ...], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


_ATTEMPT_FIELDS = frozenset(
    {
        "attempt_id",
        "engine",
        "provider",
        "capture_profile",
        "browser",
        "browser_version",
        "network",
        "result_type",
        "evidence",
        "eot_to_playback_started_ms",
        "barge_in_to_audio_stopped_ms",
        "reconnect_to_active_ms",
        "abnormal_terminal",
        "voiced_sample_silent_loss",
        "correctness_violations",
    }
)


def load_turn_attempts_jsonl(content: str) -> tuple[TurnAttempt, ...]:
    """Parse strict JSONL evidence without silently dropping malformed attempts."""

    attempts: list[TurnAttempt] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on quality evidence line {line_number}") from error
        if not isinstance(payload, dict):
            raise TypeError(f"quality evidence line {line_number} must be an object")
        fields = frozenset(payload)
        if fields != _ATTEMPT_FIELDS:
            missing = sorted(_ATTEMPT_FIELDS - fields)
            unexpected = sorted(fields - _ATTEMPT_FIELDS)
            raise ValueError(
                f"quality evidence line {line_number} has invalid fields; "
                f"missing={missing}, unexpected={unexpected}"
            )
        violations = payload["correctness_violations"]
        if not isinstance(violations, list):
            raise TypeError(
                f"quality evidence line {line_number} correctness_violations must be a list"
            )
        try:
            attempts.append(
                TurnAttempt(
                    attempt_id=payload["attempt_id"],
                    engine=payload["engine"],
                    provider=payload["provider"],
                    capture_profile=payload["capture_profile"],
                    browser=payload["browser"],
                    browser_version=payload["browser_version"],
                    network=payload["network"],
                    result_type=payload["result_type"],
                    evidence=EvidenceKind(payload["evidence"]),
                    eot_to_playback_started_ms=payload["eot_to_playback_started_ms"],
                    barge_in_to_audio_stopped_ms=payload["barge_in_to_audio_stopped_ms"],
                    reconnect_to_active_ms=payload["reconnect_to_active_ms"],
                    abnormal_terminal=payload["abnormal_terminal"],
                    voiced_sample_silent_loss=payload["voiced_sample_silent_loss"],
                    correctness_violations=tuple(violations),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid quality evidence on line {line_number}: {error}") from error
    return tuple(attempts)


def quality_report_to_dict(report: VoiceRuntimeQualityReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "attempted_turns": report.attempted_turns,
        "live_attempted_turns": report.live_attempted_turns,
        "minimum_attempted_turns_per_profile": (report.minimum_attempted_turns_per_profile),
        "required_browsers": list(report.required_browsers),
        "slo_thresholds": {
            "eot_to_playback_p50_ms": EOT_TO_PLAYBACK_P50_MS_MAX_EXCLUSIVE,
            "eot_to_playback_p95_ms": EOT_TO_PLAYBACK_P95_MS_MAX_EXCLUSIVE,
            "barge_in_stop_p95_ms": BARGE_IN_STOP_P95_MS_MAX_EXCLUSIVE,
            "reconnect_p95_ms": RECONNECT_P95_MS_MAX_EXCLUSIVE,
            "abnormal_terminal_rate": ABNORMAL_TERMINAL_RATE_MAX_EXCLUSIVE,
            "correctness_violation_count": 0,
        },
        "profiles": [
            {
                "engine": profile.key.engine,
                "provider": profile.key.provider,
                "capture_profile": profile.key.capture_profile,
                "live_attempted_turns": profile.live_attempted_turns,
                "observed_browsers": list(profile.observed_browsers),
                "missing_required_browsers": list(profile.missing_required_browsers),
                "sample_coverage_passed": profile.sample_coverage_passed,
            }
            for profile in report.profiles
        ],
        "groups": [
            {
                "engine": group.key.engine,
                "provider": group.key.provider,
                "capture_profile": group.key.capture_profile,
                "browser": group.key.browser,
                "browser_version": group.key.browser_version,
                "network": group.key.network,
                "result_type": group.key.result_type,
                "evidence": group.key.evidence.value,
                "attempted_turns": group.attempted_turns,
                "eot_to_playback_p50_ms": group.eot_to_playback_p50_ms,
                "eot_to_playback_p95_ms": group.eot_to_playback_p95_ms,
                "barge_in_stop_p95_ms": group.barge_in_stop_p95_ms,
                "reconnect_p95_ms": group.reconnect_p95_ms,
                "abnormal_terminal_rate": group.abnormal_terminal_rate,
                "correctness_violation_count": group.correctness_violation_count,
                "slo_passed": group.slo_passed,
            }
            for group in report.groups
        ],
    }


def render_quality_report_markdown(report: VoiceRuntimeQualityReport) -> str:
    lines = [
        "# Voice Runtime Quality Report",
        "",
        f"Status: **{report.status.value.upper()}**",
        "",
        f"- Attempted turns: {report.attempted_turns}",
        f"- Live attempted turns: {report.live_attempted_turns}",
        f"- Minimum live attempts per Profile: {report.minimum_attempted_turns_per_profile}",
        f"- Required browsers: {', '.join(report.required_browsers) or 'none'}",
        "",
        "## Profile coverage",
        "",
        "| Engine | Provider | Capture profile | Live attempts | Browsers | Missing | Coverage |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for profile in report.profiles:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(profile.key.engine),
                    _markdown(profile.key.provider),
                    _markdown(profile.key.capture_profile),
                    str(profile.live_attempted_turns),
                    _markdown(", ".join(profile.observed_browsers) or "—"),
                    _markdown(", ".join(profile.missing_required_browsers) or "—"),
                    "PASS" if profile.sample_coverage_passed else "PREVIEW",
                )
            )
            + " |"
        )
    if not report.profiles:
        missing = _markdown(", ".join(report.required_browsers) or "—")
        lines.append(f"| — | — | — | 0 | — | {missing} | PREVIEW |")
    lines.extend(
        (
            "",
            "## SLO groups",
            "",
            "| Engine / provider / profile | Browser | Network | Result | Evidence | N | EOT→playback p50/p95 | Barge p95 | Reconnect p95 | Abnormal | Violations | SLO |",
            "| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        )
    )
    for group in report.groups:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(
                        f"{group.key.engine} / {group.key.provider} / {group.key.capture_profile}"
                    ),
                    _markdown(f"{group.key.browser} {group.key.browser_version}"),
                    _markdown(group.key.network),
                    _markdown(group.key.result_type),
                    group.key.evidence.value,
                    str(group.attempted_turns),
                    f"{_format_ms(group.eot_to_playback_p50_ms)} / {_format_ms(group.eot_to_playback_p95_ms)}",
                    _format_ms(group.barge_in_stop_p95_ms),
                    _format_ms(group.reconnect_p95_ms),
                    f"{group.abnormal_terminal_rate:.3%}",
                    str(group.correctness_violation_count),
                    "PASS" if group.slo_passed else "FAIL",
                )
            )
            + " |"
        )
    if not report.groups:
        lines.append("| — | — | — | — | — | 0 | — | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def _format_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} ms"


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
