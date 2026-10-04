import type { ConversationReplayItem } from "./admin-diagnostics";
import type { DebugLogTimeline, SessionDetail, TelemetryEvent } from "./observability";

export interface SessionDiagnosticsReport {
  schema_version: 1;
  collection_health?: import("./observability").CollectionHealth | null;
  session_id: string;
  telemetry: SessionDetail | null;
  conversation: ConversationReplayItem[];
  debug_log: DebugLogTimeline | null;
  sources: Record<"telemetry" | "conversation" | "debug_log", { status: "available" | "unavailable" | "not-found"; truncated: boolean; error?: string }>;
  audio: { status: "not-configured" };
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
