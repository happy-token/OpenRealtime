import { describe, expect, it } from "vitest";
import { exactDuration, interruptionEvents, measuredSpans, mergeDiagnosticsPage, recordingCollectionNotice, type SessionDiagnosticsReport } from "./session-diagnostics-report";
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


describe("recording collection status without inventing replay availability", () => {
  it.each([
    ["not-configured", false, "未配置录音存储"],
    ["failed", true, "可能不完整"],
    ["active", false, "临时录音存储"],
    ["settled", false, "临时录音存储"],
    ["active", true, "已启用录音采集"],
    ["settled", true, "已启用录音采集"],
  ])("reports %s with durable=%s", (status, durable, expected) => {
    const item = event("recording", "recording.status", 1000, null);
    item.attributes = { status, storage_durable: durable };
    const notice = recordingCollectionNotice([item]);
    expect(notice).toContain(expected);
    expect(notice).not.toContain("该策略尚未启用");
  });
  it("uses the latest valid observation even across out-of-order pages", () => {
    const old = event("old", "recording.status", 1000, null); old.attributes = { status: "active", storage_durable: true };
    const recent = event("recent", "recording.status", 2000, null); recent.attributes = { status: "failed" };
    const invalid = { ...old, occurred_at: "invalid" };
    expect(recordingCollectionNotice([old, recent, invalid])).toContain("录音采集异常");
    expect(recordingCollectionNotice([])).toContain("无法确认");
  });
});

it("preserves an authoritative failure later within the same millisecond across pages", () => {
  const active = event("active", "recording.status", 1000, null);
  active.occurred_at = "2026-10-07T00:00:00.123100+00:00";
  active.sequence = 1; active.attributes = { status: "active", storage_durable: true };
  const failed = { ...active, event_id: "failed", occurred_at: "2026-10-07T00:00:00.123900+00:00", sequence: 2, attributes: { status: "failed" } };
  expect(recordingCollectionNotice([active, failed])).toContain("录音采集异常");
  expect(recordingCollectionNotice([failed, active])).toContain("录音采集异常");
});

it("preserves microsecond ordering even when separate telemetry bindings reset sequence", () => {
  const active = event("active", "recording.status", 1000, null);
  active.sequence = 1; active.occurred_at = "2026-10-07T00:00:00.123100+00:00";
  active.attributes = { status: "active", storage_durable: true };
  const failed = { ...active, event_id: "failed", occurred_at: "2026-10-07T00:00:00.123900+00:00", attributes: { status: "failed" } };
  expect(recordingCollectionNotice([active, failed])).toContain("录音采集异常");
  expect(recordingCollectionNotice([failed, active])).toContain("录音采集异常");
});

it("merges only requested input evidence, deduplicates retries and retains failed cursors", () => {
  const previous = emptyReport();
  const record = { item_id: "e1", voice_session_id: "session-1", sequence: "1", occurred_at: "2026-10-07T00:00:00Z", detail: { generation: 1 } };
  previous.input_evidence = { schema: "semantic-input-evidence.v1", voice_session_id: "session-1", records: [record], next_cursor: "1", durable: false, status: "available" };
  previous.sources.input_evidence = { status: "available", truncated: true };
  const next = emptyReport(); next.input_evidence = { ...previous.input_evidence, records: [record, { ...record, item_id: "e2", sequence: "2" }], next_cursor: null };
  next.sources.input_evidence = { status: "available", truncated: false };
  const params = new URLSearchParams({ input_cursor: "1" });
  const merged = mergeDiagnosticsPage(previous, next, params);
  expect(merged.input_evidence?.records.map(row => row.item_id)).toEqual(["e1", "e2"]);
  expect(merged.input_evidence?.next_cursor).toBeNull();
  expect(mergeDiagnosticsPage(merged, next, params).input_evidence?.records).toHaveLength(2);
  expect(mergeDiagnosticsPage(previous, next, new URLSearchParams({ conversation_cursor: "1" })).input_evidence).toBe(previous.input_evidence);
  next.sources.input_evidence.status = "unavailable"; next.input_evidence = null;
  expect(mergeDiagnosticsPage(previous, next, params).input_evidence).toBe(previous.input_evidence);
});
