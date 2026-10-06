import { describe, expect, it } from "vitest";
import { exactDuration, interruptionEvents, measuredSpans } from "./session-diagnostics-report";
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
