import { describe, expect, it } from "vitest";
import { buildLatencyGroups, buildReplayTurns, buildSessionMetricAggregates, buildSessionPipelineStages, buildTurnLatencyAnalysis } from "./admin-diagnostics";
import type { MetricAggregate, SessionDetail } from "./observability";

function metric(name: string, p50: number, p95: number, sampleCount = 4): MetricAggregate {
  return {
    name,
    sample_count: sampleCount,
    p50_ms: p50,
    p95_ms: p95,
    p99_ms: p95 + 20,
    max_ms: p95 + 40,
    timeout_count: 0,
    error_count: 0,
    cancelled_count: 0,
    degraded_count: 0,
  };
}

describe("buildLatencyGroups", () => {
  it("projects provider-specific telemetry into stable ASR, LLM, TTS and end-to-end groups", () => {
    const groups = buildLatencyGroups([
      metric("asr.final_tail", 120, 280),
      metric("provider.deepseek.chat.stream", 610, 1_420),
      metric("tts.time_to_first_audio", 230, 540),
      metric("turn.endpoint_to_client_playback", 1_440, 2_360),
    ]);

    expect(groups).toHaveLength(6);
    expect(groups).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "asr", p50_ms: 120, p95_ms: 280, sample_count: 4 }),
      expect.objectContaining({ id: "llm", p50_ms: 610, p95_ms: 1_420, sample_count: 4 }),
      expect.objectContaining({ id: "tts", p50_ms: 230, p95_ms: 540, sample_count: 4 }),
      expect.objectContaining({ id: "e2e", p50_ms: 1_440, p95_ms: 2_360, sample_count: 4 }),
    ]));
  });
});

describe("buildTurnLatencyAnalysis", () => {
  it("attributes a stutter to network or upstream delivery when chunk gaps are high", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00Z", last_event_at: "2026-08-12T12:00:01Z", turn_count: 1, timeout_count: 0, error_count: 0, no_response_count: 0, event_count: 1 },
      events: [{ event_id: "e1", sequence: 1, name: "client.playback_quality", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: null, response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: { arrival_jitter_ms: 45, max_chunk_gap_ms: 180, underrun_count: 2, underrun_total_ms: 60 } }],
    } satisfies SessionDetail;

    expect(buildTurnLatencyAnalysis(detail)[0]).toEqual(expect.objectContaining({
      max_chunk_gap_ms: 180,
      playback_cause: "network_or_upstream",
    }));
  });
});

describe("session performance projection", () => {
  it("aggregates one session into P50, P95, P99, max and failure counts", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00Z", last_event_at: "2026-08-12T12:00:04Z", turn_count: 2, timeout_count: 1, error_count: 0, no_response_count: 0, event_count: 4 },
      events: [
        { event_id: "e1", sequence: 1, name: "engine.time_to_first_text", kind: "milestone", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01Z", duration_ms: 120, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "e2", sequence: 2, name: "engine.time_to_first_text", kind: "milestone", outcome: "timeout", severity: "warning", voice_session_id: "s1", generation: 2, turn_id: "t2", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:02Z", duration_ms: 480, timeout_ms: 400, error_type: "TimeoutError", error_message: "late", attributes: {} },
        { event_id: "e3", sequence: 3, name: "engine.time_to_first_text", kind: "milestone", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 3, turn_id: "t3", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:03Z", duration_ms: 260, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "ignored", sequence: 4, name: "asr.partial", kind: "event", outcome: "ok", severity: "debug", voice_session_id: "s1", generation: 3, turn_id: "t3", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:04Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
      ],
    } satisfies SessionDetail;

    expect(buildSessionMetricAggregates(detail)).toEqual([
      expect.objectContaining({ name: "engine.time_to_first_text", sample_count: 3, p50_ms: 260, p95_ms: 480, p99_ms: 480, max_ms: 480, timeout_count: 1, error_count: 0 }),
    ]);
  });

  it("maps session metrics to the latency-critical voice pipeline", () => {
    const stages = buildSessionPipelineStages([
      metric("asr.start_session", 85, 130),
      metric("turn.speech_to_endpoint_commit", 210, 390),
      metric("engine.time_to_first_text", 510, 880),
      metric("tts.connection_setup", 90, 160),
      metric("tts.time_to_first_audio", 180, 310),
      metric("turn.endpoint_to_client_playback", 920, 1_450),
    ]);

    expect(stages.map((stage) => [stage.id, stage.metric_name, stage.p95_ms])).toEqual([
      ["asr_connect", "asr.start_session", 130],
      ["endpoint", "turn.speech_to_endpoint_commit", 390],
      ["model", "engine.time_to_first_text", 880],
      ["tts_connect", "tts.connection_setup", 160],
      ["tts_audio", "tts.time_to_first_audio", 310],
      ["playback", "turn.endpoint_to_client_playback", 1_450],
    ]);
  });
});

describe("buildReplayTurns", () => {
  it("projects exact dialogue-state changes and the user end-of-turn boundary onto the timeline", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00.000Z", last_event_at: "2026-08-12T12:00:02.000Z", turn_count: 1, timeout_count: 0, error_count: 0, no_response_count: 0, event_count: 2 },
      events: [
        { event_id: "listen", sequence: 1, name: "turn_policy_transition", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:00.125Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: { from_state: "idle", to_state: "listen", transition: "τ1", signal: "USER_SPEECH_ONSET" } },
        { event_id: "commit", sequence: 2, name: "turn_policy_transition", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01.040Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: { from_state: "listen", to_state: "speak", transition: "τ3", signal: "USER_EOT_CONFIRMED" } },
      ],
    } satisfies SessionDetail;

    const [turn] = buildReplayTurns(detail, [{ item_id: "u1", role: "user", text: "帮我查天气", generation: 1, status: "committed", occurred_at: "2026-08-12T12:00:00.000Z" }]);

    expect(turn.timeline_events).toEqual([
      expect.objectContaining({ event_id: "listen", label: "用户开始表达", elapsed_ms: 125, state_change: "IDLE → LISTEN", turn_boundary: false }),
      expect.objectContaining({ event_id: "commit", label: "用户表达完成 · 轮次确认", elapsed_ms: 1040, state_change: "LISTEN → SPEAK", turn_boundary: true }),
    ]);
  });

  it("keeps the full event history while promoting latency-critical milestones in time order", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00.000Z", last_event_at: "2026-08-12T12:00:02.000Z", turn_count: 1, timeout_count: 0, error_count: 0, no_response_count: 0, event_count: 4 },
      events: [
        { event_id: "tts", sequence: 3, name: "tts.time_to_first_audio", kind: "milestone", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01.500Z", duration_ms: 200, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "raw", sequence: 2, name: "turn_policy.evaluate", kind: "span", outcome: "ok", severity: "debug", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:00.300Z", duration_ms: 1, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "endpoint", sequence: 1, name: "endpoint_candidate_started", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:00.250Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "model", sequence: 4, name: "engine.time_to_first_text", kind: "milestone", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01.200Z", duration_ms: 560, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
      ],
    } satisfies SessionDetail;

    const [turn] = buildReplayTurns(detail, [{ item_id: "u1", role: "user", text: "你好", generation: 1, status: "committed", occurred_at: "2026-08-12T12:00:00.000Z" }]);

    expect(turn.events).toHaveLength(4);
    expect(turn.timeline_events.map(({ name, stage, elapsed_ms }) => ({ name, stage, elapsed_ms }))).toEqual([
      { name: "endpoint_candidate_started", stage: "endpoint", elapsed_ms: 250 },
      { name: "engine.time_to_first_text", stage: "model", elapsed_ms: 1200 },
      { name: "tts.time_to_first_audio", stage: "tts", elapsed_ms: 1500 },
    ]);
  });

  it("uses the earliest real event as the turn clock origin when transcript commit arrives later", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00.000Z", last_event_at: "2026-08-12T12:00:02.000Z", turn_count: 1, timeout_count: 0, error_count: 0, no_response_count: 0, event_count: 2 },
      events: [
        { event_id: "speech", sequence: 1, name: "user_speech_started", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:00.000Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
        { event_id: "commit", sequence: 2, name: "turn_policy_transition", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:02.000Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: { from_state: "listen", to_state: "speak", transition: "τ3", signal: "USER_EOT_CONFIRMED" } },
      ],
    } satisfies SessionDetail;

    const [turn] = buildReplayTurns(detail, [{ item_id: "u1", role: "user", text: "稍后提交的文本", generation: 1, status: "committed", occurred_at: "2026-08-12T12:00:01.500Z" }]);

    expect(turn.occurred_at).toBe("2026-08-12T12:00:00.000Z");
    expect(turn.timeline_events.find((event) => event.turn_boundary)?.elapsed_ms).toBe(2000);
  });

  it("highlights the affected turn and compresses normal state transitions", () => {
    const detail = {
      summary: { voice_session_id: "s1", first_event_at: "2026-08-12T12:00:00Z", last_event_at: "2026-08-12T12:00:03Z", turn_count: 1, timeout_count: 1, error_count: 0, no_response_count: 0, event_count: 3 },
      events: [
        { event_id: "state", sequence: 1, name: "turn_policy_transition", kind: "event", outcome: "ok", severity: "info", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:01Z", duration_ms: null, timeout_ms: null, error_type: null, error_message: null, attributes: { from_state: "listen", to_state: "speak", transition: "τ3" } },
        { event_id: "timeout", sequence: 2, name: "provider.deepseek.chat.stream", kind: "provider_call", outcome: "timeout", severity: "warning", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:02Z", duration_ms: 30000, timeout_ms: 30000, error_type: "TimeoutError", error_message: "model timed out", attributes: {} },
        { event_id: "total", sequence: 3, name: "turn.total", kind: "terminal", outcome: "timeout", severity: "warning", voice_session_id: "s1", generation: 1, turn_id: "t1", response_id: null, call_id: null, worker_id: null, occurred_at: "2026-08-12T12:00:03Z", duration_ms: 30000, timeout_ms: null, error_type: null, error_message: null, attributes: {} },
      ],
    } satisfies SessionDetail;
    const turns = buildReplayTurns(detail, [{ item_id: "u1", role: "user", text: "你好", generation: 1, status: "committed", occurred_at: "2026-08-12T12:00:00Z" }]);

    expect(turns[0]).toEqual(expect.objectContaining({
      generation: 1,
      abnormal: true,
      state_summary: "LISTEN → SPEAK",
    }));
    expect(turns[0].issues[0]).toEqual(expect.objectContaining({ kind: "timeout" }));
  });
});
