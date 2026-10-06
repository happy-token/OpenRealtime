import type { SessionDiagnosticsReport } from "./session-diagnostics-report";
import type { DiagnosticsOverview, TelemetryEvent } from "./observability";
import { buildSessionMetricAggregates } from "./admin-diagnostics";
const reports: SessionDiagnosticsReport[] = Array.from({ length: 6 }, (_, i) => {
  const id = `preview-voice-${i + 1}`, start = Date.now() - (i + 1) * 900_000;
  const events: TelemetryEvent[] = [];
  const conversation: SessionDiagnosticsReport["conversation"] = [];
  for (let generation = 1; generation <= 4; generation++) {
    const at = start + generation * 10_000;
    for (const [index, [name, duration, end]] of [
      ["asr.speech_start_to_first_text", 480, 155], ["asr.last_frame_to_final_text", 125, 155],
      ["llm.request_to_first_text", generation === 2 ? 680 : 280, 620], ["tts.first_text_to_first_audio", 140, 760],
      ["semantic_interruption.classify", 110, 250], ["turn.speech_end_to_client_playback", generation === 2 ? 1180 : 760, 1240],
      ...(generation === 3 ? [["barge_in.speech_start_to_client_stop", 420, 1300]] : []), ["turn_policy.eot_classify", 95, 250], ["memory.retrieve", 25, 275], ["knowledge.retrieve", 60, 310],
      ["brain.time_to_first_text", generation === 2 ? 730 : 310, generation === 2 ? 1040 : 620], ["tts.time_to_first_audio", 140, generation === 2 ? 1180 : 760],
      ["turn.endpoint_to_client_playback", generation === 2 ? 1060 : 640, generation === 2 ? 1240 : 820],
      ...(generation === 3 ? [["barge_in.time_to_client_stop", 240, 1300]] : []),
    ].entries()) {
      events.push({ event_id: `${id}-${generation}-${index}`, sequence: events.length + 1, name: String(name), kind: "span", outcome: "ok", severity: "info", voice_session_id: id, generation, turn_id: `turn-${generation}`, response_id: null, call_id: null, worker_id: null, occurred_at: new Date(at + Number(end)).toISOString(), duration_ms: Number(duration), timeout_ms: null, error_type: null, error_message: null, attributes: {} });
    }
    conversation.push({ item_id: `${id}-user-${generation}`, role: "user", text: ["帮我整理今天的安排。", "这段能说得简短一些吗？", "等等，先说最重要的事情。", "好的，我先处理这个。"][generation - 1], generation, status: "committed", occurred_at: new Date(at).toISOString() });
    conversation.push({ item_id: `${id}-assistant-${generation}`, role: "assistant", text: ["可以，我们先从最重要的事项开始。", "好的，我用三点说明。", "先完成刚才提到的那项任务。", "需要时我可以帮你继续拆解。"][generation - 1], generation, status: "committed", occurred_at: new Date(at + 1400).toISOString() });
  }
  const summary = { voice_session_id: id, first_event_at: new Date(start).toISOString(), last_event_at: new Date(start + 130_000).toISOString(), turn_count: 4, timeout_count: 0, error_count: 0, no_response_count: 0, event_count: events.length };
  return { schema_version: 1, session_id: id, telemetry: { summary, events }, conversation, debug_log: { voice_session_id: id, entries: [{ event_id: `${id}-debug`, voice_session_id: id, sequence: 1, stage: "interruption", event: "confirmed", summary: "规则识别为有效打断，等待客户端 stopped 回执。", occurred_at: events[0].occurred_at, generation: 3, turn_id: "turn-3", detail: { label: "stop", source: "rule" } }] }, sources: { telemetry: { status: "available", truncated: false }, conversation: { status: "available", truncated: false }, debug_log: { status: "available", truncated: false } }, audio: { status: "not-configured" } };
});
const overview: DiagnosticsOverview = { latency_collection_ready: true, failed_turn_count: 0, capability_failures: [], module_health: ["asr", "eot", "interruption", "llm", "tts", "playback", "transport"].map(module => ({ module, error_count: 0, timeout_count: 0, disconnect_count: ["asr", "transport"].includes(module) ? 0 : null, retry_count: module === "asr" ? 0 : null, recovery_rate: null, recovered_count: 0, recovery_failed_count: 0, affected_session_count: 0 })) , since: new Date(Date.now() - 86400000).toISOString(), until: new Date().toISOString(), session_count: 6, turn_count: 24, successful_turn_count: 24, success_rate: 1, no_response_count: 0, no_response_rate: 0, timeout_count: 0, error_count: 0, cancelled_count: 0, interrupted_count: 0, degraded_count: 0, metrics: buildSessionMetricAggregates({ summary: reports[0].telemetry!.summary, events: reports.flatMap(report => report.telemetry!.events) }) };
export const diagnosticsPreview = { overview, sessions: reports.map(report => report.telemetry!.summary), reports };
