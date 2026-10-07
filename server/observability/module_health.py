"""Project recorded failures without treating missing instrumentation as zero."""
from collections.abc import Iterable, Mapping
from typing import Any

MODULES = ("asr", "eot", "interruption", "llm", "tts", "playback", "transport")


def module_for(name: str) -> str | None:
    if "eot_classifier" in name or "eot_classify" in name:
        return "eot"
    if "interruption" in name:
        return "interruption"
    if "asr" in name or ".vad" in name:
        return "asr"
    if "tts" in name:
        return "tts"
    if "deepseek" in name or "llm" in name or ".brain" in name:
        return "llm"
    if "transport" in name:
        return "transport"
    if "playback" in name or "speech_output" in name:
        return "playback"
    return None


def _failure_key(row: Mapping[str, Any]) -> tuple[str, ...] | None:
    module = module_for(str(row["name"]))
    session = row.get("voice_session_id")
    incident = row.get("incident_id") or row.get("call_id")
    if not module or not isinstance(session, str) or not session or not isinstance(incident, str) or not incident:
        return None
    return (module, str(row.get("tenant_id") or ""), str(row.get("user_id") or ""), session,
            "incident" if row.get("incident_id") else "call", incident)


def module_health(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    result: dict[str, dict[str, Any]] = {module: {"module": module, "error_count": None, "timeout_count": None,
        "disconnect_count": None, "retry_count": None, "recovery_rate": None} for module in MODULES}
    rows = list(rows)
    provider_incidents = {_failure_key(row) for row in rows
        if str(row["name"]).startswith("provider.") and row["outcome"] in ("error", "timeout")}
    provider_incidents.discard(None)
    recovered = failed = disconnected = 0
    transport_collected = False
    affected_sessions: set[str] = set()
    affected_count = 0
    asr_restart_success = asr_restart_failed = 0
    for row in rows:
        name = str(row["name"])
        module = module_for(name)
        if module is None:
            continue
        item = result[module]
        count = int(row.get("count", 1))
        # Prefer a provider fact only for a positively correlated incident.
        # Uncorrelated rows remain event counts, never guessed unique requests.
        authoritative = (name.startswith(("provider.", "realtime.capability."))
            or name in {"client.input_capture_failed", "playback.stop_handoff_failed", "playback.stop_handoff_ready"})
        duplicate = name.startswith("realtime.capability.") and _failure_key(row) in provider_incidents
        if duplicate:
            authoritative = False
        if name == "transport.collection_ready":
            transport_collected = True
        if name == "transport.disconnected":
            disconnected += count
            if row.get("voice_session_id"):
                affected_sessions.add(str(row["voice_session_id"]))
            affected_count += int(row.get("session_count", 0))
        if name == "transport.recovered":
            recovered += count
        if name == "transport.recovery_failed":
            failed += count
        if name == "asr.collection_ready":
            item["disconnect_count"] = item["disconnect_count"] or 0
            item["retry_count"] = item["retry_count"] or 0
        if name == "asr.session_restarted":
            item["retry_count"] = (item["retry_count"] or 0) + count
        if name == "asr.restart_completed":
            asr_restart_success += count
        if name == "asr.restart_failed":
            asr_restart_failed += count
        if authoritative:
            for key in ("error_count", "timeout_count"):
                if item[key] is None:
                    item[key] = 0
            if row["outcome"] in ("error", "timeout"):
                item["timeout_count" if row["outcome"] == "timeout" else "error_count"] += count
        if (not duplicate and row["outcome"] not in ("cancelled", "superseded")
            and name != "client.transport_disconnect" and (
            "disconnect" in name or "connection_lost" in name or row.get("error_type") in {
                "ConnectionError", "ConnectionClosedError", "ConnectionResetError",
                "WebSocketConnectionClosedException"})):
            item["disconnect_count"] = (item["disconnect_count"] or 0) + count
    if asr_restart_success + asr_restart_failed:
        result["asr"]["recovery_rate"] = asr_restart_success / (asr_restart_success + asr_restart_failed)
    if transport_collected:
        result["transport"].update(disconnect_count=disconnected, error_count=failed, timeout_count=0,
            recovery_rate=recovered / (recovered+failed) if recovered+failed else None,
            recovered_count=recovered, recovery_failed_count=failed,
            affected_session_count=len(affected_sessions) or affected_count)
    return tuple(result.values())
