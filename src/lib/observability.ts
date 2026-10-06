export type MetricAggregate = {
  name: string;
  sample_count: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  max_ms: number;
  timeout_count: number;
  error_count: number;
  cancelled_count: number;
  degraded_count: number;
};

export type ModuleHealth = { module: string; error_count: number | null; timeout_count: number | null; disconnect_count: number | null; retry_count: number | null; recovery_rate: number | null; recovered_count?: number; recovery_failed_count?: number; affected_session_count?: number };

export type DiagnosticsOverview = {
  module_health?: ModuleHealth[];
  failed_turn_count?: number;
  latency_collection_ready?: boolean;
  since: string;
  until: string;
  session_count: number;
  turn_count: number;
  successful_turn_count: number;
  success_rate: number | null;
  no_response_count: number;
  no_response_rate: number | null;
  timeout_count: number;
  error_count: number;
  cancelled_count: number;
  interrupted_count: number;
  degraded_count: number;
  metrics: MetricAggregate[];
  capability_failures?: { capability: string; error_count: number; timeout_count: number }[];
};

export type SessionSummary = {
  disconnect_count?: number;
  failure_names?: string[];
  voice_session_id: string;
  first_event_at: string;
  last_event_at: string;
  turn_count: number;
  timeout_count: number;
  error_count: number;
  no_response_count: number;
  event_count: number;
};

export type TelemetryEvent = {
  event_id: string;
  sequence: number;
  name: string;
  kind: "event" | "span" | "milestone" | "terminal" | "provider_call";
  outcome:
    | "ok"
    | "timeout"
    | "error"
    | "cancelled"
    | "superseded"
    | "degraded"
    | "no_response";
  severity: "debug" | "info" | "warning" | "error";
  voice_session_id: string;
  generation: number | null;
  turn_id: string | null;
  response_id: string | null;
  call_id: string | null;
  worker_id: string | null;
  occurred_at: string;
  duration_ms: number | null;
  timeout_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  attributes: Record<string, unknown>;
};

export type SessionDetail = {
  next_cursor?: string | null;
  summary: SessionSummary;
  events: TelemetryEvent[];
};

export type DebugLogStage = "eot" | "interruption" | "turn" | "playback";

export type DebugLogEntry = {
  event_id: string;
  voice_session_id: string;
  sequence: number;
  stage: DebugLogStage | string;
  event: string;
  summary: string;
  occurred_at: string;
  generation: number | null;
  turn_id: string | null;
  detail: Record<string, unknown>;
};

export type DebugLogTimeline = {
  next_cursor?: string | null;
  voice_session_id: string;
  entries: DebugLogEntry[];
};

export const STAGE_LABELS: Record<string, string> = {
  eot: "语义完整度判断",
  interruption: "语义打断判断",
  turn: "轮次终态",
  playback: "播放",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)}s`;
  return `${Math.round(value)}ms`;
}

export function formatRate(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function formatClock(value: string): string {
  if (!Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export const METRIC_LABELS: Record<string, string> = {
  "coordinator.queue_wait": "Turn 队列等待",
  "turn_policy.eot_classify": "语义判停判断耗时",
  "engine.time_to_first_text": "Engine 首文本",
  "engine.time_to_first_speakable": "首个可朗读文本",
  "tts.time_to_first_audio": "回复启动 → 首音频（含生成）",
  "tts.connection_setup": "TTS 建连",
  "engine.time_to_first_audio": "Engine 首音频",
  "turn.time_to_first_text_sent": "服务端首文本发送",
  "turn.time_to_first_audio_sent": "服务端首音频发送",
  "engine.total": "Engine 总耗时",
  "turn.total": "Turn 总耗时",
  "endpoint.commit_wait": "端点确认等待",
  "turn.speech_to_endpoint_commit": "说话开始到端点提交",
  "turn.endpoint_to_client_playback": "端点到客户端首播",
  "asr.time_to_first_partial": "ASR 首批文本",
  "asr.final_tail": "ASR 尾包等待",
  "asr.start_session": "ASR 建连",
  "router.plan": "路由规划",
  "conversation.respond": "对话生成与交付",
  "response.deliver": "响应交付",
  "semantic_interruption.classify": "语义打断判断耗时",
  "tool.policy.evaluate": "工具策略判断",
  "tool.execute": "工具执行",
  "provider.deepseek.chat.stream": "DeepSeek 流式生成",
  "provider.deepseek.tool_chat.complete": "DeepSeek 工具编排",
  "provider.doubao.tts.synthesize_stream": "豆包 TTS 流式合成",
  "provider.byte.web_search": "联网搜索",
  "barge_in.time_to_client_stop": "确认打断到停播回执",
  "barge_in.speech_start_to_client_stop": "有效打断开口到旧输出停播",
  "turn.speech_end_to_client_playback": "用户停说到客户端首播",
  "brain.time_to_first_text": "回复请求 → 首文本（含编排）",
  "memory.retrieve": "记忆检索",
  "knowledge.retrieve": "知识库检索",
  "client.network_jitter": "客户端网络抖动",
  "client.playback_underrun": "TTS 播放欠载",
  "client.transport_disconnect": "客户端断连恢复",
  "asr_session_restarted": "ASR 断连重建",
  "tts.connection_lost": "TTS 连接中断",
};

export function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name;
}


export const CORE_LATENCY_METRICS = [
  "provider.asr.connection_setup", "provider.tts.connection_setup",
  "jev.eot.slot_wait", "jev.eot.client_ready", "jev.eot.request",
  "asr.speech_start_to_first_text", "asr.last_frame_to_final_text",
  "llm.request_to_first_text", "tts.first_text_to_first_audio",
  "turn_policy.eot_classify", "semantic_interruption.classify",
  "playback.stop_request_to_receipt", "playback.stop_receipt_to_handoff", "playback.stop_request_to_handoff",
] as const;
export const METRIC_DESCRIPTIONS: Record<string, string> = {
  "playback.stop_request_to_receipt": "发送精确停播命令 → 收到匹配的本地音频队列停播回执，包含网络往返；不能证明扬声器已经物理静音。仅统计成功回执。",
  "playback.stop_receipt_to_handoff": "收到本地停播回执 → 服务端播放事实投影完成并允许交接。仅统计成功交接。",
  "playback.stop_request_to_handoff": "发送停播命令 → 服务端允许交接，包含回执延迟和投影等待；与子阶段重叠，不应重复相加。超时、未知和取消不计入成功耗时。",

  "jev.eot.slot_wait": "判停调用开始获取 JEV 并发槽位 → 获得槽位；不包含候选文本块在单飞队列中的等待。",
  "jev.eot.client_ready": "获得槽位 → SDK 客户端准备完成；HTTP 连接可能在后续请求阶段才建立。",
  "jev.eot.request": "SDK system_one 请求开始 → 完整结果返回，包含网络、HTTP 连接、服务端处理与 SDK 解析；并非纯模型推理。",
  "provider.asr.connection_setup": "ASR capability 初始化调用开始 → WebSocket 建连并发送配置完成；不代表首文本已返回。",
  "provider.tts.connection_setup": "TTS 后台预连接开始 → 提供商连接就绪；若已有连接则仅测复用检查，不计入提前完成后的首包延迟。",
  "turn_policy.eot_classify": "语义判停判断开始 → 结果返回，含规则或分类器处理，不含判停前静音等待。",
  "semantic_interruption.classify": "语义打断判断开始 → 结果返回，含规则或分类器处理，不等于客户端实际停播延迟。",
  "asr.speech_start_to_first_text": "VAD 检测到开口 → 首次非空识别文本；含识别所需音频积累与 VAD 检测误差，不含开口前静音。",
  "asr.last_frame_to_final_text": "最近一帧音频交给 ASR → 最终文本交付；不是用户停说到回复的整体延迟。",
  "asr.input_to_first_text": "该轮第一帧音频 → 首文本，可能包含长时间静音与说话；仅作链路诊断，不代表模型处理耗时。",
  "llm.request_to_first_text": "实际模型请求 → 首个非空文本增量（TTFT），不包含工具编排；当前未采集逐 Token 间隔。",
  "tts.first_text_to_first_audio": "首段非空文本交给 TTS → 首个非空音频包，包含传输与合成，不含前置 LLM 生成。",
  "provider.eot_classifier.classify": "语义判停分类器开始调用 → 判断返回，包含模型调用；规则直通不产生该模型样本。",
  "provider.interruption_classifier.classify": "语义打断分类器开始调用 → 判断返回；规则直通不产生该模型样本，不等于停播延迟。",
  "tts.time_to_first_audio": "回复启动 → 首音频事件，包含上游文本生成，不能视为纯 TTS 首包。",
  "brain.time_to_first_text": "回复请求 → 首文本事件，包含路由、检索与编排，不能视为纯 LLM TTFT。",
  "provider.deepseek.responses.stream": "DeepSeek 整次 Responses 流式请求耗时，不是首 Token 延迟。",
  "provider.deepseek.chat.stream": "DeepSeek 整次 Chat 流式请求耗时，不是首 Token 延迟。",
  "turn.speech_end_to_client_playback": "VAD 停说时刻估算 → 客户端首播回执。包含静音等待、判停、生成与交付；VAD 边界有检测误差，回执包含网络回传，不是客户端同一时钟的精确测量。",
  "barge_in.speech_start_to_client_stop": "VAD 检测开口 → 有效抢话后客户端停播回执。仅计有效打断；附和、自然结束、主动挂断不计，含 VAD 检测和回执传输误差。",
  "turn.endpoint_to_client_playback": "端点确认 → 客户端播放回执；不含端点确认前的判停等待。",
};
Object.assign(METRIC_LABELS, {
  "playback.stop_request_to_receipt": "停播回执延迟",
  "playback.stop_receipt_to_handoff": "停播投影等待",
  "playback.stop_request_to_handoff": "停播交接总等待",
  "playback.stop_requested": "发送停播命令",
  "playback.stop_receipt": "收到停播回执",
  "playback.stop_handoff_ready": "停播确认与投影已完成",
  "playback.stop_handoff_failed": "停播交接未完成",

  "jev.eot.slot_wait": "JEV 判停并发排队",
  "jev.eot.client_ready": "JEV 判停客户端准备",
  "jev.eot.request": "JEV 判停请求等待",
  "provider.asr.connection_setup": "ASR 建立连接延迟",
  "provider.tts.connection_setup": "TTS 建立连接延迟",
  "asr.speech_start_to_first_text": "ASR 首包延迟",
  "asr.input_to_first_text": "音频输入 → 首文本（含静音等待）",
  "asr.last_frame_to_final_text": "ASR 尾包延迟",
  "llm.request_to_first_text": "LLM 首文本响应（TTFT）",
  "tts.first_text_to_first_audio": "TTS 首包延迟",
  "provider.eot_classifier.classify": "语义判停模型响应",
  "provider.interruption_classifier.classify": "语义打断模型响应",
  "brain.response_started": "回复请求 → 编排启动",
  "provider.deepseek.responses.stream": "DeepSeek Responses 流式总耗时",
});
export function dashboardLatencyMetrics(metrics: MetricAggregate[]) {
  const names = [...CORE_LATENCY_METRICS, ...metrics.map(metric => metric.name).filter(name => !(CORE_LATENCY_METRICS as readonly string[]).includes(name))];
  return names.map(name => ({ name, metric: metrics.find(metric => metric.name === name) ?? null, description: METRIC_DESCRIPTIONS[name] ?? "已记录的事件或调用耗时；具体起止点请查看会话原始事件。" }));
}

export type CollectionHealth = { status: "ok" | "degraded" | "unavailable"; telemetry: { dropped_events: number; pending_events: number; write_error: boolean; storage_backend: string }; debug_log: { dropped_events: number; pending_events: number; write_error: boolean; storage_backend: string } };

export async function loadDiagnosticsOverview(minutes: number, signal: AbortSignal): Promise<{
  overview: DiagnosticsOverview | null;
  sessions: SessionSummary[];
  health: CollectionHealth | null;
  errors: string[];
}> {
  async function getJson<T>(url: string): Promise<T> {
    const response = await fetch(url, { cache: "no-store", signal });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
    return body;
  }
  const [aggregate, list, collection] = await Promise.allSettled([
    getJson<DiagnosticsOverview>(`/api/observability/overview?minutes=${minutes}`),
    getJson<SessionSummary[]>(`/api/observability/sessions?minutes=${minutes}&limit=500`),
    getJson<CollectionHealth>("/api/observability/health"),
  ]);
  const errors: string[] = [];
  const failureMessage = (label: string, reason: unknown) =>
    reason instanceof Error && reason.message ? `${label}：${reason.message}` : label;
  if (aggregate.status === "rejected") errors.push(failureMessage("总览指标暂时不可用", aggregate.reason));
  if (list.status === "rejected") errors.push(failureMessage("会话列表暂时不可用", list.reason));
  return {
    overview: aggregate.status === "fulfilled" ? aggregate.value : null,
    sessions: list.status === "fulfilled" ? list.value : [],
    health: collection.status === "fulfilled" && collection.value?.telemetry && collection.value?.debug_log ? collection.value : null,
    errors,
  };
}

export function diagnosticModule(name: string): string | null {
  if (/eot_classifier|eot_classify/.test(name)) return "eot";
  if (name.includes("interruption")) return "interruption";
  if (/asr|\.vad/.test(name)) return "asr";
  if (name.includes("tts")) return "tts";
  if (/deepseek|llm|\.brain/.test(name)) return "llm";
  if (name.includes("transport")) return "transport";
  if (/playback|speech_output/.test(name)) return "playback";
  return null;
}
