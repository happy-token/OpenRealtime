import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { issueDiagnosticsAccess } from "@/lib/diagnostics-access";
import { GET } from "./route";
const admin = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({ currentAppAdmin: admin }));
const fetchMock = vi.fn();
const secret = "recording-test-only-secret-32-characters";
const row = { voice_session_id: "session-1", artifact_id: "artifact-1", item_id: "item-1", journal_sequence: "1", direction: "input", epoch: "epoch", speech_id: null, stream_id: "stream", sample_rate_hz: 16000, channels: 1, start_sample: 0, sample_count: 160, duration_ms: 10, discontinuity: false, captured_at: "2026-10-07T00:00:00Z", retention_until: "2026-10-14T00:00:00Z", storage_durable: false, capture_boundary: "validated_input", playback_confirmation: "not-inferred", generation: 0, turn_id: "turn", response_id: null, size_bytes: 364, sha256: "a".repeat(64), status: "available", pinned: false };
const page = () => ({ voice_session_id: "session-1", items: [row], next_cursor: null, storage_status: "configured" });
const run = (query = "", headers: Record<string, string> = {}, id = "session-1") => GET(new NextRequest(`https://app.test/api/observability/sessions/session-1/recordings${query}`, { headers }), { params: Promise.resolve({ sessionId: id }) });
beforeEach(() => { vi.resetAllMocks(); vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", secret); admin.mockResolvedValue({ subject: "admin" }); vi.stubGlobal("fetch", fetchMock); fetchMock.mockResolvedValue(Response.json(page())); });
it("denies unauthenticated and invalid bearer without cookie fallback or upstream read", async () => {
  admin.mockResolvedValue(null); expect((await run()).status).toBe(403);
  admin.mockResolvedValue({ subject: "admin" }); expect((await run("", { authorization: "Bearer invalid" })).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled(); expect(admin).toHaveBeenCalledTimes(1);
});
it("accepts exact Session grant without sending it upstream", async () => {
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  const response = await run("", { authorization: `Bearer ${token}` });
  expect(response.status).toBe(200); expect(admin).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls[0][1].headers).toBeUndefined();
  expect((await run("", { authorization: `Bearer ${token}` }, "session-2")).status).toBe(403);
});
it("projects safe same-origin references and independent exact bigint cursor", async () => {
  fetchMock.mockResolvedValue(Response.json({ ...page(), items: [{ ...row, journal_sequence: "9007199254740994", object_key: "private-key", tenant_id: "owner" }], next_cursor: "9007199254740994" }));
  const response = await run("?after_sequence=9007199254740993&limit=1"), body = await response.json();
  expect(response.status).toBe(200); expect(body.next_cursor).toBe("9007199254740994");
  expect(body.items[0].audio_url).toBe("/api/observability/sessions/session-1/recordings/artifact-1/audio");
  expect(JSON.stringify(body)).not.toContain("private-key"); expect(body.items[0].tenant_id).toBeUndefined();
  expect(String(fetchMock.mock.calls[0][0])).toContain("after_sequence=9007199254740993&limit=1");
});
it.each(["?limit=201", "?limit=01", "?after_sequence=01", "?after_sequence=9223372036854775808", "?limit=1&limit=2"])("rejects invalid pagination %s", async query => { expect((await run(query)).status).toBe(400); expect(fetchMock).not.toHaveBeenCalled(); });
it.each([
  { ...page(), storage_status: ["configured"] },
  { ...page(), items: [{ ...row, direction: ["input"] }] },
  { ...page(), items: [{ ...row, status: ["available"] }] },
  { ...page(), voice_session_id: "foreign" },
  { ...page(), items: [{ ...row, voice_session_id: "foreign" }] },
  { ...page(), items: [{ ...row, artifact_id: ".." }] },
  { ...page(), next_cursor: "0" },
  { ...page(), items: [{ ...row, playback_confirmation: "played" }] },
  { ...page(), items: [{ ...row, size_bytes: 12 }] },
])("fails closed for malformed or foreign catalog", async body => { fetchMock.mockResolvedValue(Response.json(body)); expect((await run()).status).toBe(503); });
it("preserves missing/expired/unavailable transport outcomes", async () => { for (const status of [404, 410, 503]) { fetchMock.mockResolvedValue(Response.json({ secret: "do-not-expose" }, { status })); const response = await run(); expect(response.status).toBe(status); expect(await response.text()).not.toContain("do-not-expose"); } });

it("cancels an oversized metadata stream without consuming it", async () => {
  let cancelled = false;
  fetchMock.mockResolvedValue(new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { "Content-Length": "2000000" } }));
  expect((await run()).status).toBe(503); expect(cancelled).toBe(true);
});
it("projects Session preservation for readers without administrator or storage identity", async () => {
  fetchMock.mockResolvedValue(Response.json({ ...page(), preservation: { status: "preserved", marked_at: "2026-10-07T00:00:00Z", preserved_segments: 1, pending_segments: 0, unavailable_segments: 2, storage_durable: true, actor_id: "private-admin", owner_id: "private-owner" } }));
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  const response = await run("", { authorization: `Bearer ${token}` }), projected = await response.json();
  expect(response.status).toBe(200); expect(projected.preservation.status).toBe("preserved"); expect(JSON.stringify(projected)).not.toMatch(/private-/);
});
it("does not infer preserved status from an old or malformed policy response", async () => {
  expect((await (await run()).json()).preservation).toBeUndefined();
  for (const preservation of [null, { status: "preserved" }, { status: "unmarked", marked_at: null, preserved_segments: 0, pending_segments: null, unavailable_segments: null, storage_durable: true }]) {
    fetchMock.mockResolvedValue(Response.json({ ...page(), preservation })); expect((await run()).status).toBe(503);
  }
});
const sentRow = () => ({ ...row, direction: "sent", speech_id: "speech", stream_id: "speech", capture_boundary: "transport_send_completed",
  playback: { status: "reported", reported_end_sample: 80, overlap_samples: 80, sample_rate_hz: 16000 } });
const playbackSource = () => ({ status: "available", truncated: true, collection_healthy: false });
it("whitelists exact reported sample overlap and source completeness for an Agent", async () => {
  fetchMock.mockResolvedValue(Response.json({ ...page(), items: [{ ...sentRow(), playback: { ...sentRow().playback, tenant_id: "private-tenant", object_key: "private-object" } }], playback_source: { ...playbackSource(), owner_id: "private-owner" } }));
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  const response = await run("", { authorization: `Bearer ${token}` }), published = await response.json();
  expect(response.status).toBe(200); expect(published.items[0].playback).toEqual(sentRow().playback);
  expect(published.items[0].playback_confirmation).toBe("not-inferred"); expect(published.playback_source).toEqual(playbackSource());
  expect(JSON.stringify(published)).not.toContain("private-"); expect(admin).not.toHaveBeenCalled();
});
it.each([{ overlap_samples: 81 }, { reported_end_sample: true }, { overlap_samples: -1 }, { sample_rate_hz: 8000 }, { status: ["reported"] }, { status: "unknown" }, { reported_end_sample: 0 }, { reported_end_sample: 2 ** 53 }])("rejects an inconsistent reported overlap %s", async patch => {
  const sent = sentRow();
  fetchMock.mockResolvedValue(Response.json({ ...page(), items: [{ ...sent, playback: { ...sent.playback, ...patch } }], playback_source: playbackSource() }));
  expect((await run()).status).toBe(503);
});
it("requires an available source and speech-local stream for a reported overlap", async () => {
  for (const body of [
    { ...page(), items: [sentRow()] },
    { ...page(), items: [sentRow()], playback_source: { ...playbackSource(), status: "unavailable", truncated: false } },
    { ...page(), items: [{ ...sentRow(), stream_id: "foreign" }], playback_source: playbackSource() },
    { ...page(), items: [{ ...row, playback: sentRow().playback }], playback_source: playbackSource() },
  ]) { fetchMock.mockResolvedValue(Response.json(body)); expect((await run()).status).toBe(503); }
});
it("keeps unknown samples null and old backend fields absent", async () => {
  const old = await (await run()).json(); expect(old.items[0].playback).toBeUndefined(); expect(old.playback_source).toBeUndefined();
  const unknown = { status: "unknown", reported_end_sample: null, overlap_samples: null, sample_rate_hz: null };
  fetchMock.mockResolvedValue(Response.json({ ...page(), items: [{ ...sentRow(), playback: unknown }], playback_source: { ...playbackSource(), truncated: false } }));
  expect((await (await run()).json()).items[0].playback).toEqual(unknown);
});
