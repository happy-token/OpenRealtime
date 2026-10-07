import type { MetricAggregate, SessionDetail, TelemetryEvent } from "./observability";

export type LatencyGroupId = "asr" | "llm" | "tts" | "e2e" | "barge_in" | "network" | "playback";

export interface LatencyGroup {
  id: LatencyGroupId;
  label: string;
  description: string;
  metric_name: string | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  sample_count: number;
  error_count: number;
  timeout_count: number;
}

export type SessionPipelineStageId = "asr_connect" | "endpoint" | "model" | "tts_connect" | "tts_audio" | "playback";

export interface SessionPipelineStage {
  id: SessionPipelineStageId;
  label: string;
  description: string;
  metric_name: string | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  max_ms: number | null;
  sample_count: number;
  timeout_count: number;
  error_count: number;
}

export interface TurnLatencyAnalysis {
  generation: number;
  turn_id: string | null;
  occurred_at: string;
  outcome: TelemetryEvent["outcome"];
  asr_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  first_audio_ms: number | null;
  total_ms: number | null;
  network_jitter_ms: number | null;
  max_chunk_gap_ms: number | null;
  playback_underruns: number;
  playback_underrun_ms: number;
  playback_cause: "stable" | "network_or_upstream" | "terminal_scheduling";
}

export interface DiagnosticLogEntry {
  event_id: string;
  occurred_at: string;
  severity: TelemetryEvent["severity"];
  name: string;
  message: string;
  generation: number | null;
  error_type: string | null;
}

export interface ConversationReplayItem {
  item_id: string;
  voice_session_id?: string;
  role: "user" | "assistant";
  text: string;
  generation: number;
  status: string;
  occurred_at: string;
}

export interface ReplayIssue {
  event_id: string;
  kind: "timeout" | "error" | "playback" | "disconnect" | "degraded";
  label: string;
  occurred_at: string;
  detail: string;
}

export type ReplayEventStage = "input" | "endpoint" | "model" | "tts" | "playback" | "state" | "system";

export interface ReplayTimelineEvent {
  event_id: string;
  name: string;
  label: string;
  occurred_at: string;
  elapsed_ms: number;
  stage: ReplayEventStage;
  state_change: string | null;
  signal: string | null;
  turn_boundary: boolean;
  event: TelemetryEvent;
}

export interface ReplayTurn {
  generation: number;
  messages: ConversationReplayItem[];
  occurred_at: string;
  state_summary: string;
  state_events: TelemetryEvent[];
  events: TelemetryEvent[];
  timeline_events: ReplayTimelineEvent[];
  issues: ReplayIssue[];
  abnormal: boolean;
  latency: TurnLatencyAnalysis | null;
}

const GROUPS: Array<{
  id: LatencyGroupId;
  label: string;
  description: string;
  candidates: Array<string | RegExp>;
}> = [
  { id: "asr", label: "ASR 尾包", description: "用户停止到最终识别", candidates: ["asr.final_tail", "asr.time_to_first_partial"] },
  { id: "llm", label: "大模型响应", description: "请求到首段回复文本", candidates: ["engine.time_to_first_text", /^provider\..+\.chat(?:\.stream)?$/] },
  { id: "tts", label: "TTS 首音", description: "首段文本到首个音频包", candidates: ["tts.time_to_first_audio", "tts.connection_setup", /^provider\..+\.tts\./] },
  { id: "e2e", label: "端到端首音", description: "端点确认到终端开始播放", candidates: ["turn.endpoint_to_client_playback", "turn.endpoint_to_first_audio", "turn.time_to_first_audio_sent"] },
  { id: "barge_in", label: "打断响应", description: "检测到打断到客户端确认停播", candidates: ["barge_in.time_to_client_stop"] },
  { id: "network", label: "网络抖动", description: "TTS 音频块到达间隔波动", candidates: ["client.network_jitter"] },
  { id: "playback", label: "播放卡顿", description: "终端播放欠载累计时长", candidates: ["client.playback_underrun"] },
];

const SESSION_PIPELINE: Array<{
  id: SessionPipelineStageId;
  label: string;
  description: string;
  candidates: Array<string | RegExp>;
}> = [
  { id: "asr_connect", label: "ASR 建连", description: "建立语音识别会话", candidates: ["asr.start_session"] },
  { id: "endpoint", label: "轮次确认", description: "用户停说到表达完整判定", candidates: ["turn.speech_to_endpoint_commit", "endpoint.commit_wait", "turn_policy.eot_classify", "asr.final_tail"] },
  { id: "model", label: "模型首文本", description: "请求到首段回复文本", candidates: ["engine.time_to_first_text", /^provider\..+\.chat(?:\.stream)?$/] },
  { id: "tts_connect", label: "TTS 建连", description: "建立语音合成连接", candidates: ["tts.connection_setup"] },
  { id: "tts_audio", label: "TTS 首音", description: "首段文本到首个音频包", candidates: ["tts.time_to_first_audio", /^provider\..+\.tts\./] },
  { id: "playback", label: "终端首播", description: "轮次确认到用户听见声音", candidates: ["turn.endpoint_to_client_playback", "turn.endpoint_to_first_audio", "turn.time_to_first_audio_sent"] },
];

export function buildSessionMetricAggregates(detail: SessionDetail): MetricAggregate[] {
  const grouped = new Map<string, TelemetryEvent[]>();
  for (const event of detail.events) {
    if (event.duration_ms === null) continue;
    const events = grouped.get(event.name) ?? [];
    events.push(event);
    grouped.set(event.name, events);
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, events]) => {
      const durations = events
        .map((event) => event.duration_ms)
        .filter((duration): duration is number => duration !== null)
        .sort((left, right) => left - right);
      return {
        name,
        sample_count: durations.length,
        p50_ms: metricPercentile(durations, 0.5),
        p95_ms: metricPercentile(durations, 0.95),
        p99_ms: metricPercentile(durations, 0.99),
        max_ms: durations.at(-1) ?? 0,
        timeout_count: events.filter((event) => event.outcome === "timeout").length,
        error_count: events.filter((event) => event.outcome === "error").length,
        cancelled_count: events.filter((event) => event.outcome === "cancelled" || event.outcome === "superseded").length,
        degraded_count: events.filter((event) => event.outcome === "degraded").length,
      };
    });
}

export function buildSessionPipelineStages(metrics: MetricAggregate[]): SessionPipelineStage[] {
  return SESSION_PIPELINE.map((stage) => {
    const metric = findMetric(metrics, stage.candidates);
    return {
      id: stage.id,
      label: stage.label,
      description: stage.description,
      metric_name: metric?.name ?? null,
      p50_ms: metric?.p50_ms ?? null,
      p95_ms: metric?.p95_ms ?? null,
      p99_ms: metric?.p99_ms ?? null,
      max_ms: metric?.max_ms ?? null,
      sample_count: metric?.sample_count ?? 0,
      timeout_count: metric?.timeout_count ?? 0,
      error_count: metric?.error_count ?? 0,
    };
  });
}

export function buildLatencyGroups(metrics: MetricAggregate[]): LatencyGroup[] {
  return GROUPS.map((group) => {
    const metric = findMetric(metrics, group.candidates);
    return {
      id: group.id,
      label: group.label,
      description: group.description,
      metric_name: metric?.name ?? null,
      p50_ms: metric?.p50_ms ?? null,
      p95_ms: metric?.p95_ms ?? null,
      p99_ms: metric?.p99_ms ?? null,
      sample_count: metric?.sample_count ?? 0,
      error_count: metric?.error_count ?? 0,
      timeout_count: metric?.timeout_count ?? 0,
    };
  });
}

export function buildTurnLatencyAnalysis(detail: SessionDetail): TurnLatencyAnalysis[] {
  const grouped = new Map<number, TelemetryEvent[]>();
  for (const event of detail.events) {
    if (event.generation === null || event.generation < 1) continue;
    const events = grouped.get(event.generation) ?? [];
    events.push(event);
    grouped.set(event.generation, events);
  }
  return [...grouped.entries()]
    .map(([generation, events]) => {
      const terminal = [...events].reverse().find((event) => event.name === "turn.total");
      const playback = events.find((event) => event.name === "client.playback_quality");
      const networkJitterMs = numberAttribute(playback, "arrival_jitter_ms");
      const maxChunkGapMs = numberAttribute(playback, "max_chunk_gap_ms");
      const playbackUnderruns = numberAttribute(playback, "underrun_count") ?? 0;
      const playbackCause: TurnLatencyAnalysis["playback_cause"] = playbackUnderruns === 0
        ? "stable"
        : ((networkJitterMs ?? 0) >= 30 || (maxChunkGapMs ?? 0) >= 120)
          ? "network_or_upstream"
          : "terminal_scheduling";
      return {
        generation,
        turn_id: terminal?.turn_id ?? events.find((event) => event.turn_id)?.turn_id ?? null,
        occurred_at: terminal?.occurred_at ?? events[0]?.occurred_at ?? detail.summary.first_event_at,
        outcome: terminal?.outcome ?? "ok",
        asr_ms: duration(events, ["asr.final_tail"]),
        llm_ms: duration(events, ["engine.time_to_first_text", /^provider\..+\.chat(?:\.stream)?$/]),
        tts_ms: duration(events, ["tts.time_to_first_audio"]),
        first_audio_ms: duration(events, ["turn.endpoint_to_client_playback", "turn.endpoint_to_first_audio", "turn.time_to_first_audio_sent"]),
        total_ms: terminal?.duration_ms ?? duration(events, ["engine.total"]),
        network_jitter_ms: networkJitterMs,
        max_chunk_gap_ms: maxChunkGapMs,
        playback_underruns: playbackUnderruns,
        playback_underrun_ms: numberAttribute(playback, "underrun_total_ms") ?? 0,
        playback_cause: playbackCause,
      };
    })
    .sort((left, right) => left.generation - right.generation);
}

export function buildDiagnosticLogs(detail: SessionDetail): DiagnosticLogEntry[] {
  return detail.events
    .filter((event) => (
      event.outcome !== "cancelled" &&
      event.outcome !== "superseded" &&
      (event.severity === "warning" || event.severity === "error" || event.error_message)
    ))
    .map((event) => ({
      event_id: event.event_id,
      occurred_at: event.occurred_at,
      severity: event.severity,
      name: event.name,
      message: event.error_message ?? stringAttribute(event, "message") ?? event.outcome,
      generation: event.generation,
      error_type: event.error_type,
    }))
    .reverse();
}

export function buildReplayTurns(
  detail: SessionDetail,
  conversation: ConversationReplayItem[],
): ReplayTurn[] {
  const latencies = new Map(
    buildTurnLatencyAnalysis(detail).map((turn) => [turn.generation, turn]),
  );
  const generations = new Set<number>();
  conversation.forEach((item) => item.generation > 0 && generations.add(item.generation));
  detail.events.forEach((event) => {
    if (event.generation !== null && event.generation > 0) generations.add(event.generation);
  });

  return [...generations].sort((a, b) => a - b).map((generation) => {
    const messages = conversation.filter((item) => item.generation === generation);
    const events = detail.events.filter((event) => event.generation === generation);
    const stateEvents = events.filter((event) => event.name === "turn_policy_transition");
    const occurredAt = earliestTimestamp(
      [...messages.map((message) => message.occurred_at), ...events.map((event) => event.occurred_at)],
      detail.summary.first_event_at,
    );
    const issues = events.flatMap(issueFromEvent);
    const latency = latencies.get(generation) ?? null;
    if (latency?.playback_underruns && !issues.some((issue) => issue.kind === "playback")) {
      issues.push({
        event_id: `playback-${generation}`,
        kind: "playback",
        label: "TTS 播放不稳定",
        occurred_at: latency.occurred_at,
        detail: `${latency.playback_underruns} 次欠载，累计 ${Math.round(latency.playback_underrun_ms)}ms`,
      });
    }
    return {
      generation,
      messages,
      occurred_at: occurredAt,
      state_summary: stateSummary(stateEvents),
      state_events: stateEvents,
      events: [...events].sort((left, right) => Date.parse(left.occurred_at) - Date.parse(right.occurred_at)),
      timeline_events: events
        .map((event) => timelineEventFromTelemetry(event, occurredAt))
        .filter((event): event is ReplayTimelineEvent => event !== null)
        .sort((left, right) => left.elapsed_ms - right.elapsed_ms),
      issues,
      abnormal: issues.length > 0,
      latency,
    };
  });
}

const TIMELINE_EVENT_META: Record<string, { label: string; stage: ReplayEventStage }> = {
  "playback.stop_requested": { label: "发送停播命令", stage: "playback" },
  "playback.stop_receipt": { label: "收到停播回执", stage: "playback" },
  "playback.stop_handoff_ready": { label: "停播确认与投影已完成", stage: "playback" },
  "playback.stop_handoff_failed": { label: "停播交接未完成", stage: "playback" },

  user_speech_started: { label: "用户开始说话", stage: "input" },
  "vad.silence_window": { label: "检测到静音窗口", stage: "endpoint" },
  vad_endpoint_confirmed: { label: "VAD 确认语音停止", stage: "endpoint" },
  asr_idle_stop_confirmed: { label: "ASR 静默确认", stage: "endpoint" },
  endpoint_candidate_started: { label: "开始判断表达完整性", stage: "endpoint" },
  "turn_policy.eot_classify": { label: "语义完整度判断", stage: "endpoint" },
  eot_classifier_deferred: { label: "等待用户继续表达", stage: "endpoint" },
  endpoint_candidate_invalidated: { label: "检测到继续表达", stage: "endpoint" },
  endpoint_committed: { label: "表达确认并提交", stage: "endpoint" },
  "asr.final_tail": { label: "ASR 最终文本", stage: "input" },
  "router.plan": { label: "路由决策", stage: "model" },
  "conversation.respond": { label: "生成回复", stage: "model" },
  "engine.time_to_first_text": { label: "模型返回首文本", stage: "model" },
  "tts.connection_setup": { label: "TTS 建立连接", stage: "tts" },
  "tts.time_to_first_audio": { label: "TTS 返回首音频", stage: "tts" },
  "response.deliver": { label: "开始交付回复", stage: "playback" },
  "turn.time_to_first_audio_sent": { label: "服务端发送首音频", stage: "playback" },
  "turn.endpoint_to_client_playback": { label: "终端开始播放", stage: "playback" },
  "client.playback_quality": { label: "终端播放质量", stage: "playback" },
  "turn.total": { label: "本轮处理完成", stage: "system" },
};

function timelineEventFromTelemetry(event: TelemetryEvent, turnStartedAt: string): ReplayTimelineEvent | null {
  if (event.name === "turn_policy_transition") return timelineEventFromState(event, turnStartedAt);
  let meta = TIMELINE_EVENT_META[event.name];
  if (!meta && /^provider\..+\.chat(?:\.stream|\.complete)?$/.test(event.name)) {
    meta = { label: "模型服务调用", stage: "model" };
  } else if (!meta && /^provider\..+\.tts\./.test(event.name)) {
    meta = { label: "TTS 服务调用", stage: "tts" };
  } else if (!meta && (event.severity === "warning" || event.severity === "error")) {
    meta = { label: metricLabelFallback(event.name), stage: "system" };
  }
  if (!meta) return null;
  return {
    event_id: event.event_id,
    name: event.name,
    label: meta.label,
    occurred_at: event.occurred_at,
    elapsed_ms: elapsedMilliseconds(event.occurred_at, turnStartedAt),
    stage: meta.stage,
    state_change: null,
    signal: null,
    turn_boundary: false,
    event,
  };
}

function timelineEventFromState(event: TelemetryEvent, turnStartedAt: string): ReplayTimelineEvent {
  const signal = stringAttribute(event, "signal");
  const fromState = stringAttribute(event, "from_state")?.toUpperCase() ?? null;
  const toState = stringAttribute(event, "to_state")?.toUpperCase() ?? null;
  const turnBoundary = signal === "USER_EOT_CONFIRMED";
  return {
    event_id: event.event_id,
    name: event.name,
    label: turnBoundary
      ? "用户表达完成 · 轮次确认"
      : signal === "USER_SPEECH_ONSET"
        ? "用户开始表达"
        : metricLabelFallback(event.name),
    occurred_at: event.occurred_at,
    elapsed_ms: elapsedMilliseconds(event.occurred_at, turnStartedAt),
    stage: "state",
    state_change: fromState && toState ? `${fromState} → ${toState}` : null,
    signal,
    turn_boundary: turnBoundary,
    event,
  };
}

function elapsedMilliseconds(occurredAt: string, startedAt: string): number {
  return Math.max(0, Date.parse(occurredAt) - Date.parse(startedAt));
}

function earliestTimestamp(values: string[], fallback: string): string {
  if (!values.length) return fallback;
  return values.slice(1).reduce(
    (earliest, value) => Date.parse(value) < Date.parse(earliest) ? value : earliest,
    values[0],
  );
}

function stateSummary(events: TelemetryEvent[]): string {
  if (!events.length) return "状态记录不可用";
  const states: string[] = [];
  for (const event of events) {
    const from = stringAttribute(event, "from_state")?.toUpperCase();
    const to = stringAttribute(event, "to_state")?.toUpperCase();
    if (from && states.at(-1) !== from) states.push(from);
    if (to && states.at(-1) !== to) states.push(to);
  }
  return states.length ? states.join(" → ") : `${events.length} 次状态切换`;
}

function issueFromEvent(event: TelemetryEvent): ReplayIssue[] {
  let kind: ReplayIssue["kind"] | null = null;
  let label = "";
  if (event.outcome === "timeout") {
    kind = "timeout";
    label = "服务超时";
  } else if (event.outcome === "error" || event.outcome === "no_response") {
    kind = "error";
    label = event.outcome === "no_response" ? "没有生成回复" : "服务错误";
  } else if (/disconnect|connection_lost|session_restarted/.test(event.name)) {
    kind = "disconnect";
    label = "连接中断";
  } else if (event.outcome === "degraded") {
    kind = "degraded";
    label = "降级运行";
  }
  if (!kind) return [];
  return [{
    event_id: event.event_id,
    kind,
    label,
    occurred_at: event.occurred_at,
    detail: event.error_message ?? metricLabelFallback(event.name),
  }];
}

function metricLabelFallback(name: string): string {
  return name.replaceAll(".", " / ");
}

function findMetric(metrics: MetricAggregate[], candidates: Array<string | RegExp>): MetricAggregate | undefined {
  for (const candidate of candidates) {
    const found = metrics.find((metric) => typeof candidate === "string" ? metric.name === candidate : candidate.test(metric.name));
    if (found) return found;
  }
  return undefined;
}

function metricPercentile(values: number[], quantile: number): number {
  const index = Math.max(0, Math.ceil(quantile * values.length) - 1);
  return values[index] ?? 0;
}

function duration(events: TelemetryEvent[], candidates: Array<string | RegExp>): number | null {
  for (const candidate of candidates) {
    const event = events.find((item) => typeof candidate === "string" ? item.name === candidate : candidate.test(item.name));
    if (event?.duration_ms !== null && event?.duration_ms !== undefined) return event.duration_ms;
  }
  return null;
}

function numberAttribute(event: TelemetryEvent | undefined, name: string): number | null {
  const value = event?.attributes[name];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringAttribute(event: TelemetryEvent, name: string): string | null {
  const value = event.attributes[name];
  return typeof value === "string" ? value : null;
}
