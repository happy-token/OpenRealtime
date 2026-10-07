import { createHash } from "node:crypto";
import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";
const admin = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({ currentAppAdmin: admin }));
const fetchMock = vi.fn();
const wav = Buffer.alloc(364); wav.write("RIFF");
const hash = createHash("sha256").update(wav).digest("hex");
const upstream = (changes = {}) => new Response(wav, { headers: { "Content-Type": "audio/wav", "Content-Length": "364", "X-Recording-Session": "session-1", "X-Recording-Artifact": "artifact-1", "X-Recording-SHA256": hash, ...changes } });
const run = (range?: string, artifactId = "artifact-1") => GET(new NextRequest("https://app.test/api/audio", { headers: range ? { Range: range } : {} }), { params: Promise.resolve({ sessionId: "session-1", artifactId }) });
beforeEach(() => { vi.resetAllMocks(); admin.mockResolvedValue({ subject: "admin" }); vi.stubGlobal("fetch", fetchMock); fetchMock.mockResolvedValue(upstream()); });
it("requires authorization and valid artifact before fetch", async () => { admin.mockResolvedValue(null); expect((await run()).status).toBe(403); admin.mockResolvedValue({ subject: "admin" }); expect((await run(undefined, "..")).status).toBe(400); expect(fetchMock).not.toHaveBeenCalled(); });
it("returns only verified audio with private no-store policy", async () => { const response = await run(); expect(response.status).toBe(200); expect(Buffer.from(await response.arrayBuffer())).toEqual(wav); expect(response.headers.get("Cache-Control")).toBe("no-store"); expect(response.headers.get("Content-Type")).toBe("audio/wav"); });
it.each([{ "X-Recording-Session": "foreign" }, { "X-Recording-Artifact": "foreign" }, { "X-Recording-SHA256": "b".repeat(64) }, { "Content-Length": "400" }, { "Content-Length": "4194400" }, { "Content-Type": "text/html" }])("refuses mismatched identity/integrity/size before publication", async headers => { fetchMock.mockResolvedValue(upstream(headers)); expect((await run()).status).toBe(503); });
it.each([ ["bytes=2-5", 2, 5], ["bytes=360-", 360, 363], ["bytes=-4", 360, 363] ] as const)("serves verified single range %s", async (range, start, end) => { const response = await run(range); expect(response.status).toBe(206); expect(response.headers.get("Content-Range")).toBe(`bytes ${start}-${end}/364`); expect(Buffer.from(await response.arrayBuffer())).toEqual(wav.subarray(start, end + 1)); });
it.each(["bytes=999-", "bytes=5-2", "bytes=0-1,3-4", "bytes=-0", "bytes=-999999999999999999999999", "nonsense"])("rejects unsupported or unsatisfiable range %s", async range => { const response = await run(range); expect(response.status).toBe(416); expect(response.headers.get("Content-Range")).toBe("bytes */364"); });

it("cancels an unread failed source without waiting for cancellation completion", async () => {
  let cancelled = false;
  const body = new ReadableStream({ cancel() { cancelled = true; return new Promise(() => {}); } });
  fetchMock.mockResolvedValue(new Response(body, { headers: { "X-Recording-Session": "foreign" } }));
  expect((await run()).status).toBe(503); expect(cancelled).toBe(true);
});
it("cancels an oversized header before reading any audio", async () => {
  let cancelled = false;
  const body = new ReadableStream({ cancel() { cancelled = true; } });
  fetchMock.mockResolvedValue(new Response(body, { headers: { "Content-Type": "audio/wav", "Content-Length": "5000000", "X-Recording-Session": "session-1", "X-Recording-Artifact": "artifact-1", "X-Recording-SHA256": hash } }));
  expect((await run()).status).toBe(503); expect(cancelled).toBe(true);
});

it("allows audio for the exact Session Agent grant and rejects foreign Session without fallback", async () => {
  const { issueDiagnosticsAccess } = await import("@/lib/diagnostics-access");
  const secret = "audio-test-only-secret-more-than-32-chars";
  vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", secret);
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  const request = new NextRequest("https://app.test/api/audio", { headers: { Authorization: `Bearer ${token}` } });
  expect((await GET(request, { params: Promise.resolve({ sessionId: "session-1", artifactId: "artifact-1" }) })).status).toBe(200);
  expect((await GET(request, { params: Promise.resolve({ sessionId: "foreign", artifactId: "artifact-1" }) })).status).toBe(403);
  expect(admin).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].headers).toBeUndefined();
});
