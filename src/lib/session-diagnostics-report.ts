import type { ConversationReplayItem } from "./admin-diagnostics";
import type { DebugLogTimeline, SessionDetail, TelemetryEvent } from "./observability";

export interface SessionDiagnosticsReport {
  schema_version: 1;
  collection_health?: import("./observability").CollectionHealth | null;
  session_id: string;
  telemetry: SessionDetail | null;
  conversation: ConversationReplayItem[];
  conversation_next_cursor?: string | null;
  debug_log: DebugLogTimeline | null;
  sources: Record<"telemetry" | "conversation" | "debug_log", { status: "available" | "unavailable" | "not-found"; truncated: boolean; error?: string }>;
  audio: { status: "not-configured" | "not-queried"; catalog_url?: string };
}

/** Only advance requested sources; keep existing records across page retries. */
export function mergeDiagnosticsPage(previous: SessionDiagnosticsReport, next: SessionDiagnosticsReport, params: URLSearchParams): SessionDiagnosticsReport {
  if (previous.session_id !== next.session_id) return previous;
  const merge = <T,>(before: T[], after: T[], key: (item: T) => string) => [...new Map([...before, ...after].map(item => [key(item), item])).values()];
  const telemetry = params.has("telemetry_cursor"), debug = params.has("debug_cursor"), conversation = params.has("conversation_cursor");
  return {
    ...previous, collection_health: next.collection_health,
    sources: { ...previous.sources, ...(telemetry ? { telemetry: next.sources.telemetry } : {}),
      ...(debug ? { debug_log: next.sources.debug_log } : {}), ...(conversation ? { conversation: next.sources.conversation } : {}) },
    telemetry: telemetry && next.telemetry ? { ...next.telemetry, events: merge(previous.telemetry?.events ?? [], next.telemetry.events, item => item.event_id) } : previous.telemetry,
    debug_log: debug && next.debug_log ? { ...next.debug_log, entries: merge(previous.debug_log?.entries ?? [], next.debug_log.entries, item => item.event_id) } : previous.debug_log,
    conversation: conversation && next.sources.conversation.status === "available" ? merge(previous.conversation, next.conversation, item => item.item_id) : previous.conversation,
    conversation_next_cursor: conversation && next.sources.conversation.status === "available" ? next.conversation_next_cursor : previous.conversation_next_cursor,
  };
}
export function measuredSpans(events: TelemetryEvent[]) {
  const spans = events.filter(event => event.duration_ms !== null && Number.isFinite(event.duration_ms) && event.duration_ms >= 0 && Number.isFinite(Date.parse(event.occurred_at)));
  if (!spans.length) return [];
  const origin = Math.min(...spans.map(event => Date.parse(event.occurred_at) - event.duration_ms!));
  return spans.map(event => ({ event, start: Date.parse(event.occurred_at) - event.duration_ms! - origin, duration: event.duration_ms! }));
}
export function exactDuration(events: TelemetryEvent[], name: string): number | null {
  const event = events.find(event => event.name === name && event.duration_ms !== null && Number.isFinite(event.duration_ms) && event.duration_ms >= 0);
  return event?.duration_ms ?? null;
}

export function interruptionEvents(events: TelemetryEvent[]): TelemetryEvent[] {
  return events.filter(event => event.name.startsWith("barge_in.") || event.name.startsWith("playback.stop_") || event.name.includes("interrupt"));
}


/** Collection status is separate from the still-unavailable audio replay API. */
export function recordingCollectionNotice(events: TelemetryEvent[]): string {
  // Python timestamps retain microseconds; Date.parse alone would hide a
  // failure recorded later within the same millisecond. Sequence breaks exact ties.
  const microRemainder = (at: string) => Number((at.match(/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/)?.[1] ?? "").padEnd(6, "0").slice(3));
  const latest = events.filter(event => event.name === "recording.status" && Number.isFinite(Date.parse(event.occurred_at)))
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)
      || microRemainder(b.occurred_at) - microRemainder(a.occurred_at)
      || (Number.isSafeInteger(b.sequence) ? b.sequence : 0) - (Number.isSafeInteger(a.sequence) ? a.sequence : 0))[0];
  if (latest?.attributes.status === "not-configured") return "此会话未配置录音存储，无法回放。";
  if (latest?.attributes.status === "failed") return "此会话录音采集异常，已保存的片段可能不完整。";
  if (latest?.attributes.status === "active" || latest?.attributes.status === "settled") {
    if (latest.attributes.storage_durable === false) return "此会话使用临时录音存储，服务重启后不保留。";
    if (latest.attributes.storage_durable === true) return "此会话已启用录音采集，录音保留 7 天，标记保留的录音可长期保存。";
  }
  return "当前数据未包含可确认的录音采集状态，无法确认此会话是否已录音。";
}
