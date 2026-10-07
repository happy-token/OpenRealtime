import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";
const authorize = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({ currentAppAdmin: authorize }));
const fetchMock = vi.fn();
beforeEach(() => { vi.resetAllMocks(); authorize.mockResolvedValue({ subject: "admin" }); vi.stubGlobal("fetch", fetchMock); });
const run = (id = "session-1") => GET(new NextRequest("https://app.example/api/observability/sessions/session-1/diagnostics"), { params: Promise.resolve({ sessionId: id }) });
it("denies unauthenticated requests without querying logs", async () => {
  authorize.mockResolvedValue(null); expect((await run()).status).toBe(403); expect(fetchMock).not.toHaveBeenCalled();
});
it("rejects malformed session IDs", async () => { expect((await run("../secret")).status).toBe(400); expect(fetchMock).not.toHaveBeenCalled(); });
it("preserves useful telemetry when conversation and debug log fail", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [] })).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(Response.json({}, { status: 404 }));
  const response = await run(), report = await response.json();
  expect(response.status).toBe(200); expect(report.sources.telemetry.status).toBe("available"); expect(report.sources.conversation.status).toBe("unavailable"); expect(report.sources.debug_log.status).toBe("not-found"); expect(report.audio.status).toBe("not-configured");
});
it("returns 503 for an infrastructure outage and 404 when no source exists", async () => {
  fetchMock.mockRejectedValue(new Error("offline")); expect((await run()).status).toBe(503);
  fetchMock.mockResolvedValue(Response.json({}, { status: 404 })); expect((await run()).status).toBe(404);
});
it("marks capped logs as potentially truncated rather than claiming completeness", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: Array(5000).fill({}) })).mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [], next_cursor: null })).mockResolvedValueOnce(Response.json({ entries: Array(2000).fill({}) }));
  const report = await (await run()).json(); expect(report.sources.telemetry.truncated).toBe(true); expect(report.sources.debug_log.truncated).toBe(true);
});

it("isolates malformed upstream responses from the detail page", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ events: [] })).mockResolvedValueOnce(Response.json({ items: [] })).mockResolvedValueOnce(Response.json({ entries: null }));
  const response = await run();
  expect(response.status).toBe(503);
  const report = await response.json();
  expect(report.telemetry).toBeNull();
  expect(report.conversation).toEqual([]);
  expect(report.debug_log).toBeNull();
});

it("returns not found when telemetry is absent and the other sources are empty", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 404 })).mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [], next_cursor: null })).mockResolvedValueOnce(Response.json({ entries: [] }));
  expect((await run()).status).toBe(404);
});

it("forwards independent cursors and preserves explicit page completeness", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [], next_cursor: null })).mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [], next_cursor: null })).mockResolvedValueOnce(Response.json({ entries: [], next_cursor: "next-debug" })).mockResolvedValueOnce(Response.json({ status: "degraded", telemetry: { dropped_events: 1 }, debug_log: { dropped_events: 0 } }));
  const response = await GET(new NextRequest("https://app.example/api/observability/sessions/session-1/diagnostics?telemetry_cursor=event-1&debug_cursor=debug-1"), { params: Promise.resolve({ sessionId: "session-1" }) });
  const report = await response.json();
  expect(String(fetchMock.mock.calls[0][0])).toContain("?cursor=event-1");
  expect(String(fetchMock.mock.calls[2][0])).toContain("cursor=debug-1");
  expect(report.sources.telemetry.truncated).toBe(false);
  expect(report.sources.debug_log.truncated).toBe(true);
  expect(report.collection_health.status).toBe("degraded");
});

it("preserves precise stop identity and failure metadata for the Session ID API", async () => {
  const event = { event_id: "stop-failure", name: "playback.stop_handoff_failed", generation: 3,
    turn_id: "original-turn", response_id: "response-1", call_id: "stop-1", duration_ms: null,
    outcome: "timeout", attributes: { stop_command_id: "stop-1", output_epoch: "epoch",
      speech_id: "response:response-1", state: "STOP_CONFIRMED", played_position_samples: 1200,
      reason_code: "playback_projection_deadline", handoff: "denied", observed_wait_ms: 1500 } };
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [event] }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [], next_cursor: null })).mockResolvedValueOnce(Response.json({ entries: [] }))
    .mockResolvedValueOnce(Response.json({ status: "ok" }));
  const response = await run();
  expect(response.status).toBe(200);
  expect((await response.json()).telemetry.events).toEqual([event]);
});

const replayItem = (sequence: string) => ({ item_id: `item-${sequence}`, voice_session_id: "session-1", journal_sequence: sequence,
  role: "user", text: "continued text", generation: 1, status: "committed", occurred_at: "2026-10-07T00:00:00Z" });
const runPage = (cursor: string) => GET(new NextRequest(`https://app.example/api/observability/sessions/session-1/diagnostics?conversation_cursor=${cursor}`), { params: Promise.resolve({ sessionId: "session-1" }) });
it("returns independent conversation pagination and preserves bigint sequences as strings", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [] }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [replayItem("9007199254740994")], next_cursor: "9007199254740994" }))
    .mockResolvedValueOnce(Response.json({ entries: [] }));
  const response = await runPage("9007199254740993"), report = await response.json();
  expect(response.status).toBe(200);
  expect(String(fetchMock.mock.calls[1][0])).toContain("/conversation-page?limit=200&after_sequence=9007199254740993");
  expect(report.conversation[0].journal_sequence).toBe("9007199254740994");
  expect(report.conversation_next_cursor).toBe("9007199254740994");
  expect(report.sources.conversation.truncated).toBe(true);
});
it.each(["-1", "01", "", "9223372036854775808", "1&conversation_cursor=2", "not-a-sequence"])("rejects invalid conversation cursor %s before fetching", async cursor => {
  expect((await runPage(cursor)).status).toBe(400);
  expect(fetchMock).not.toHaveBeenCalled();
});
it.each([
  { items: [], next_cursor: "1" }, { items: [], next_cursor: "0" },
  { items: [replayItem("1")], next_cursor: null }, { items: [replayItem("3"), replayItem("2")], next_cursor: "3" },
  { items: [replayItem("3")], next_cursor: "2" }, { items: [], next_cursor: "9223372036854775808" },
  { items: [replayItem("2")], next_cursor: undefined }, { items: Array.from({ length: 201 }, (_, index) => replayItem(String(index + 2))), next_cursor: "202" },
])("isolates malformed/regressive conversation pages without leaking their text", async page => {
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [] }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", ...page }))
    .mockResolvedValueOnce(Response.json({ entries: [] }));
  const response = await runPage("1"), report = await response.json();
  expect(response.status).toBe(200);
  expect(report.sources.conversation.status).toBe("unavailable");
  expect(report.conversation).toEqual([]);
  expect(report.conversation_next_cursor).toBeNull();
});

it("continues through a valid empty projected page without falsely returning 404", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 404 }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [], next_cursor: "200" }))
    .mockResolvedValueOnce(Response.json({ entries: [] }));
  const first = await run(), report = await first.json();
  expect(first.status).toBe(200);
  expect(report.conversation_next_cursor).toBe("200");
  expect(report.sources.conversation.truncated).toBe(true);
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 404 }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [replayItem("201")], next_cursor: null }))
    .mockResolvedValueOnce(Response.json({ entries: [] }));
  const second = await runPage(report.conversation_next_cursor);
  expect(second.status).toBe(200);
  expect((await second.json()).conversation[0].item_id).toBe("item-201");
});
