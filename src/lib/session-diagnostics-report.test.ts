import { describe, expect, it } from "vitest";
import { exactDuration, interruptionEvents, measuredSpans, mergeDiagnosticsPage, type SessionDiagnosticsReport } from "./session-diagnostics-report";
import type { TelemetryEvent } from "./observability";
function event(id: string, name: string, at: number, duration: number | null): TelemetryEvent {
  return { event_id: id, name, occurred_at: new Date(at).toISOString(), duration_ms: duration, generation: 1, attributes: {}, outcome: "ok" } as TelemetryEvent;
}
describe("real diagnostic timing", () => {
  it("preserves overlapping measured spans and excludes events without timing", () => {
    const spans = measuredSpans([event("a", "llm", 1000, 500), event("b", "tts", 900, 200), event("c", "state", 800, null)]);
    expect(spans.map(span => [span.start, span.duration])).toEqual([[0, 500], [200, 200]]);
  });
  it("excludes non-finite and negative durations", () => {
    const events = [event("a", "llm", 1000, Infinity), event("b", "tts", 1000, -1)];
    expect(measuredSpans(events)).toEqual([]);
    expect(exactDuration(events, "llm")).toBeNull();
  });
  it("does not replace an absent user-experience metric with a server proxy", () => {
    const events = [event("a", "barge_in.time_to_client_stop", 1000, 120)];
    expect(exactDuration(events, "barge_in.speech_start_to_client_stop")).toBeNull();
    expect(exactDuration(events, "barge_in.time_to_client_stop")).toBe(120);
  });
  it("includes precise stop facts in interruption details without inventing durations", () => {
    const events = [event("a", "barge_in.time_to_client_stop", 1000, 120),
      event("b", "playback.stop_handoff_failed", 1100, null), event("c", "asr.transcript_delta", 1200, null)];
    events[1].attributes = { observed_wait_ms: 1500, state: "STOP_UNKNOWN" };
    expect(interruptionEvents(events).map(item => item.event_id)).toEqual(["a", "b"]);
    expect(exactDuration(events, "playback.stop_request_to_handoff")).toBeNull();
    expect(measuredSpans(events).map(span => span.event.event_id)).toEqual(["a"]);
  });
});

function emptyReport(id = "session-1"): SessionDiagnosticsReport {
  return { schema_version: 1, session_id: id, conversation: [], conversation_next_cursor: null, telemetry: null,
    debug_log: { voice_session_id: id, entries: [] }, audio: { status: "not-configured" },
    sources: { telemetry: { status: "unavailable", truncated: false }, conversation: { status: "available", truncated: false }, debug_log: { status: "available", truncated: false } } };
}
function message(id: string, text: string) {
  return { item_id: id, text, role: "user" as const, generation: 1, status: "committed", occurred_at: "2026-10-07T00:00:00Z" };
}
it("advances only the requested conversation source and deduplicates retries", () => {
  const previous = emptyReport(); previous.conversation = [message("one", "original")];
  previous.conversation_next_cursor = "1"; previous.sources.conversation.truncated = true;
  previous.debug_log!.next_cursor = "retain-debug";
  const next = emptyReport(); next.conversation = [message("one", "original"), message("two", "continuation")];
  next.debug_log!.next_cursor = "not-requested";
  const params = new URLSearchParams({ conversation_cursor: "1" });
  const merged = mergeDiagnosticsPage(previous, next, params);
  expect(merged.conversation.map(item => item.item_id)).toEqual(["one", "two"]);
  expect(merged.conversation_next_cursor).toBeNull();
  expect(merged.sources.conversation.truncated).toBe(false);
  expect(merged.debug_log).toBe(previous.debug_log);
  expect(mergeDiagnosticsPage(merged, next, params).conversation).toHaveLength(2);
});
it("keeps conversation cursor and rows when only log pages were requested", () => {
  const previous = emptyReport(); previous.conversation = [message("one", "original")]; previous.conversation_next_cursor = "99";
  const next = emptyReport(); next.conversation = [message("other", "not requested")];
  const result = mergeDiagnosticsPage(previous, next, new URLSearchParams({ debug_cursor: "event-1" }));
  expect(result.conversation).toBe(previous.conversation);
  expect(result.conversation_next_cursor).toBe("99");
});
it("does not merge a late response from another Session", () => {
  const previous = emptyReport(); const foreign = emptyReport("session-2"); foreign.conversation = [message("foreign", "other Session")];
  expect(mergeDiagnosticsPage(previous, foreign, new URLSearchParams({ conversation_cursor: "1" }))).toBe(previous);
});

it("advances successful pages while retaining failed source rows and retry cursor", () => {
  const previous = emptyReport(); previous.conversation = [message("one", "saved")];
  previous.conversation_next_cursor = "1"; previous.debug_log!.next_cursor = "retry-debug";
  previous.debug_log!.entries = [{ event_id: "saved-debug" }] as NonNullable<SessionDiagnosticsReport["debug_log"]>["entries"];
  const next = emptyReport(); next.conversation = [message("two", "new")];
  next.debug_log = null; next.sources.debug_log = { status: "unavailable", truncated: false };
  const merged = mergeDiagnosticsPage(previous, next, new URLSearchParams({ conversation_cursor: "1", debug_cursor: "retry-debug" }));
  expect(merged.conversation.map(item => item.item_id)).toEqual(["one", "two"]);
  expect(merged.conversation_next_cursor).toBeNull();
  expect(merged.debug_log).toBe(previous.debug_log);
  expect(merged.sources.debug_log.status).toBe("unavailable");
  next.conversation = []; next.sources.conversation = { status: "unavailable", truncated: false };
  const failed = mergeDiagnosticsPage(previous, next, new URLSearchParams({ conversation_cursor: "1" }));
  expect(failed.conversation).toBe(previous.conversation);
  expect(failed.conversation_next_cursor).toBe("1");
});
