import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";
import { GET } from "../route";
import { issueDiagnosticsAccess } from "@/lib/diagnostics-access";

const authorize = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({ currentAppAdmin: authorize }));
const fetchMock = vi.fn();
const secret = "test-only-independent-access-secret-32-characters";
const context = (sessionId = "session-1") => ({ params: Promise.resolve({ sessionId }) });
const mint = (origin: string | null = "https://app.example", agentId = "debug-agent") => POST(new NextRequest(
  `https://app.example/api/observability/sessions/session-1/diagnostics/access?agent_id=${encodeURIComponent(agentId)}`,
  { method: "POST", headers: origin === null ? {} : { origin } }), context());
const read = (token: string, sessionId = "session-1", query = "") => GET(new NextRequest(
  `https://app.example/api/observability/sessions/${sessionId}/diagnostics${query}`,
  { headers: { authorization: `Bearer ${token}` } }), context(sessionId));
beforeEach(() => {
  vi.resetAllMocks(); vi.unstubAllEnvs();
  authorize.mockResolvedValue({ subject: "admin" });
  vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", secret);
  vi.stubGlobal("fetch", fetchMock);
});

it("delegates only one Session to a machine, independent of browser/admin services", async () => {
  const response = await mint(), grant = await response.json();
  expect(response.status).toBe(201);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(grant).toMatchObject({ session_id: "session-1", agent_id: "debug-agent", scope: "session-diagnostics:read", token_type: "Bearer" });
  authorize.mockReset().mockRejectedValue(new Error("admin DB offline"));
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [], next_cursor: "more-events" }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [{ voice_session_id: "session-1", item_id: "user-1", journal_sequence: "1", generation: 1, role: "user", text: "test", status: "committed", occurred_at: "2026-10-07T00:00:00Z" }], next_cursor: null }))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", entries: [], next_cursor: "more-debug" }))
    .mockResolvedValueOnce(Response.json({ schema: "semantic-input-evidence.v1", voice_session_id: "session-1", records: [], next_cursor: null, status: "not_collected", durable: false }));
  const reportResponse = await read(grant.access_token, "session-1", "?telemetry_cursor=event-1&debug_cursor=debug-1");
  expect(reportResponse.status).toBe(200);
  expect(authorize).not.toHaveBeenCalled();
  const report = await reportResponse.json();
  expect(report.telemetry.next_cursor).toBe("more-events");
  expect(report.debug_log.next_cursor).toBe("more-debug");
  expect(report.conversation[0].text).toBe("test");
  expect(report.collection_health).toBeNull();
  expect(report.input_evidence.status).toBe("not_collected");
  expect(fetchMock).toHaveBeenCalledTimes(4);
  expect(fetchMock.mock.calls.every(([url, options]) => String(url).includes("/sessions/session-1") && !options.headers)).toBe(true);
  expect(JSON.stringify(report)).not.toContain(grant.access_token);
  expect(String(fetchMock.mock.calls[0][0])).toContain("cursor=event-1");
  expect(String(fetchMock.mock.calls[2][0])).toContain("cursor=debug-1");
});
it("does not fall back to a valid admin cookie for an explicit invalid machine grant", async () => {
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  for (const value of [token + "x", issueDiagnosticsAccess("session-1", "agent", secret, Date.now() - 900_000).access_token])
    expect((await read(value)).status).toBe(403);
  expect((await read(token, "session-2")).status).toBe(403);
  expect(authorize).not.toHaveBeenCalled();
  expect(fetchMock).not.toHaveBeenCalled();
});
it("rejects query-string credentials, malformed headers and wrong-session identifiers before fetching", async () => {
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  authorize.mockResolvedValue(null);
  const queryResponse = await GET(new NextRequest(`https://app.example/api/observability/sessions/session-1/diagnostics?access_token=${token}`), context());
  expect(queryResponse.status).toBe(403);
  for (const authorization of ["", "Basic test", `Bearer  ${token}`, `Bearer ${token} extra`]) {
    const response = await GET(new NextRequest("https://app.example/api/observability/sessions/session-1/diagnostics", { headers: { authorization } }), context());
    expect(response.status).toBe(403);
  }
  expect((await read(token, "../secret")).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("refuses cross-origin/missing-origin signing and anonymous or machine-only signing", async () => {
  for (const origin of [null, "https://evil.example", "null"]) expect((await mint(origin)).status).toBe(403);
  authorize.mockResolvedValue(null);
  expect((await mint()).status).toBe(403);
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  expect((await POST(new NextRequest("https://app.example/api/observability/sessions/session-1/diagnostics/access", {
    method: "POST", headers: { authorization: `Bearer ${token}`, origin: "https://app.example" },
  }), context())).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("uses the actual HTTP authority when Next normalizes a local URL", async () => {
  const request = new NextRequest("http://localhost:3029/api/observability/sessions/session-1/diagnostics/access", {
    method: "POST", headers: { host: "127.0.0.1:3029", origin: "http://127.0.0.1:3029", "sec-fetch-site": "same-origin" },
  });
  expect((await POST(request, context())).status).toBe(201);
});
it.each<Record<string, string>>([
  { host: "127.0.0.1:3029", origin: "http://localhost:3029" },
  { host: "127.0.0.1:3029", origin: "http://127.0.0.1:3030" },
  { host: "127.0.0.1:3029", origin: "http://127.0.0.1:3029", "sec-fetch-site": "cross-site" },
  { host: "localhost:3029", origin: "http://evil.example", "x-forwarded-host": "evil.example" },
  { host: "evil.example/path", origin: "http://evil.example" },
])("rejects mismatched or malformed signing authority: %j", async headers => {
  const request = new NextRequest("http://localhost:3029/api/observability/sessions/session-1/diagnostics/access", { method: "POST", headers });
  expect((await POST(request, context())).status).toBe(403);
});
it("fails safely on admin-service/config outages and invalid signing identities", async () => {
  authorize.mockRejectedValueOnce(new Error("secret DB detail"));
  const outage = await mint(); expect(outage.status).toBe(503);
  expect(await outage.text()).not.toContain("secret DB detail");
  expect((await mint("https://app.example", "*")).status).toBe(400);
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", "");
  expect((await mint()).status).toBe(503);
  expect((await read(token)).status).toBe(403);
  vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", "rotated-independent-secret-32-characters");
  expect((await read(token)).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("denies dot-segment Sessions before URL normalization can change the resource", async () => {
  for (const id of [".", ".."]) {
    const request = new NextRequest("https://app.example/api/observability/sessions/placeholder/diagnostics/access", {
      method: "POST", headers: { origin: "https://app.example" },
    });
    expect((await POST(request, context(id))).status).toBe(400);
    expect((await GET(new NextRequest("https://app.example/api/observability/sessions/placeholder/diagnostics"), context(id))).status).toBe(400);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

it.each(["telemetry", "conversation", "debug_log"] as const)("refuses wrong-session %s data even from an otherwise valid upstream response", async source => {
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  const telemetry = { summary: { voice_session_id: "session-1" }, events: source === "telemetry" ? [{ voice_session_id: "session-2", text: "foreign secret" }] : [] };
  const conversation = source === "conversation" ? [{ voice_session_id: "session-2", text: "foreign secret" }] : [];
  const debug = { voice_session_id: "session-1", entries: source === "debug_log" ? [{ voice_session_id: "session-2", text: "foreign secret" }] : [] };
  for (const value of [telemetry, { voice_session_id: "session-1", items: conversation, next_cursor: null }, debug]) fetchMock.mockResolvedValueOnce(Response.json(value));
  const response = await read(token), report = await response.json();
  expect(response.status).toBe(200);
  expect(report.sources[source].status).toBe("unavailable");
  expect(JSON.stringify(report)).not.toContain("foreign secret");
});

it("does not expose legacy thread rows without verifiable Session provenance to a machine", async () => {
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  fetchMock.mockResolvedValueOnce(Response.json({ summary: { voice_session_id: "session-1" }, events: [] }))
    .mockResolvedValueOnce(Response.json([{ generation: 1, text: "unscoped thread row" }]))
    .mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", entries: [] }));
  const report = await (await read(token)).json();
  expect(report.sources.conversation.status).toBe("unavailable");
  expect(report.conversation).toEqual([]);
});
