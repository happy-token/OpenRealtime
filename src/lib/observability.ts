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

export type DiagnosticsOverview = {
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
};

export type SessionSummary = {
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
  summary: SessionSummary;
  events: TelemetryEvent[];
};

export function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)}s`;
  return `${Math.round(value)}ms`;
}

export function formatRate(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function formatClock(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export const METRIC_LABELS: Record<string, string> = {
  "coordinator.queue_wait": "Turn 队列等待",
  "turn_policy.eot_classify": "语义完整度判断",
  "engine.time_to_first_text": "Engine 首文本",
  "engine.time_to_first_speakable": "首个可朗读文本",
  "tts.time_to_first_audio": "TTS 首音频",
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
  "semantic_interruption.classify": "语义打断判断",
  "tool.policy.evaluate": "工具策略判断",
  "tool.execute": "工具执行",
  "provider.deepseek.chat.stream": "DeepSeek 流式生成",
  "provider.deepseek.tool_chat.complete": "DeepSeek 工具编排",
  "provider.doubao.tts.synthesize_stream": "豆包 TTS 流式合成",
  "provider.byte.web_search": "联网搜索",
  "barge_in.time_to_client_stop": "打断到客户端停播",
  "client.network_jitter": "客户端网络抖动",
  "client.playback_underrun": "TTS 播放欠载",
  "client.transport_disconnect": "客户端断连恢复",
  "asr_session_restarted": "ASR 断连重建",
  "tts.connection_lost": "TTS 连接中断",
};

export function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name;
}
