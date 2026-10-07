import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash, createHmac } from "node:crypto";
import { issueDiagnosticsAccess } from "@/lib/diagnostics-access";
import { POST } from "./route";
const admin = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({ currentAppAdmin: admin }));
const fetchMock = vi.fn();
const result = () => ({ voice_session_id: "session-1", preserved: true, marked_at: "2026-10-07T00:00:00Z", preserved_segments: 3, pending_segments: 1, unavailable_segments: 2, storage_durable: true });
const run = (headers: Record<string, string> = {}, body?: string, id = "session-1") => POST(new NextRequest("https://app.test/api/observability/sessions/session-1/recordings/preservation", {
  method: "POST", headers: { origin: "https://app.test", ...headers }, body,
}), { params: Promise.resolve({ sessionId: id }) });
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("fetch", fetchMock); vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 107).toString("base64url"));
  vi.stubEnv("VOICEAGENT_CONTROL_PLANE_URL", "http://127.0.0.1:8766");
  admin.mockResolvedValue({ issuer: "issuer", subject: "admin" }); fetchMock.mockResolvedValue(Response.json(result()));
});
it("accepts a current admin and sends a Session/body-bound private proof without cookies", async () => {
  const response = await run(), published = await response.json();
  expect(response.status).toBe(200); expect(response.headers.get("cache-control")).toBe("no-store");
  expect(published.status).toBe("preserved");
  const [url, options] = fetchMock.mock.calls[0];
  expect(String(url)).toBe("http://127.0.0.1:8766/observability/sessions/session-1/recordings/preservation");
  expect(options.method).toBe("POST"); expect(options.redirect).toBe("error");
  expect(JSON.parse(options.body).actor_id).toBe(createHash("sha256").update(JSON.stringify(["issuer", "admin"])).digest("hex"));
  const key = createHmac("sha256", Buffer.alloc(32, 107)).update("openrealtime/session-recording-preservation/key/v1").digest();
  expect(options.headers["X-Recording-Preservation-Signature"]).toBe(createHmac("sha256", key).update(`session-recording-preservation-v1\0${options.headers["X-Recording-Preservation-Timestamp"]}\0session-1\0${options.body}`).digest("hex"));
  expect(options.headers.authorization).toBeUndefined(); expect(options.headers.cookie).toBeUndefined();
  expect(JSON.stringify(published)).not.toContain("Signature");
});
it("rejects every Authorization header including valid read grants without cookie fallback", async () => {
  const secret = "test-read-grant-secret-with-32-characters";
  vi.stubEnv("OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET", secret);
  const token = issueDiagnosticsAccess("session-1", "agent", secret).access_token;
  for (const authorization of ["", "Bearer bad", `Bearer ${token}`]) expect((await run({ authorization })).status).toBe(403);
  expect(admin).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});
it("accepts an empty transport body without accepting client actor parameters", async () => {
  expect((await run({}, "")).status).toBe(200);
});
it("validates the wire Host when Next normalizes a loopback URL to localhost", async () => {
  const response = await POST(new NextRequest("http://localhost:3029/api/observability/sessions/session-1/recordings/preservation", {
    method: "POST", headers: { host: "127.0.0.1:3029", origin: "http://127.0.0.1:3029", "sec-fetch-site": "same-origin" },
  }), { params: Promise.resolve({ sessionId: "session-1" }) });
  expect(response.status).toBe(200);
});
it.each(["foreign.test", "app.test@evil.test", "app.test/path", "", "app.test,evil.test"])("does not fall back from a foreign/malformed wire Host %s", async host => {
  expect((await run({ host })).status).toBe(403);
  expect(admin).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});
it("does not authorize a foreign Origin through forwarded headers", async () => {
  expect((await run({ host: "app.test", origin: "https://foreign.test", "x-forwarded-host": "foreign.test" })).status).toBe(403);
  expect(admin).not.toHaveBeenCalled();
});
it.each<Record<string, string>>([{ origin: "https://evil.test" }, { origin: "null" }, { origin: "" }, { "sec-fetch-site": "cross-site" }])("rejects CSRF origins %s", async headers => {
  expect((await run(headers)).status).toBe(403); expect(admin).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});
it("rejects nonadmins, unavailable identity service, invalid IDs and client actor input", async () => {
  admin.mockResolvedValue(null); expect((await run()).status).toBe(403);
  admin.mockRejectedValue(new Error("secret")); expect((await run()).status).toBe(503);
  admin.mockResolvedValue({ issuer: "issuer", subject: "admin" });
  expect((await run({}, undefined, "..")).status).toBe(400);
  expect((await run({}, '{"actor_id":"spoof"}')).status).toBe(400);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("fails closed before sending when the shared proof key or private address is invalid", async () => {
  for (const key of ["", "bad", "!".repeat(43)]) {
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", key); expect((await run()).status).toBe(503);
  }
  vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 107).toString("base64url"));
  vi.stubEnv("VOICEAGENT_CONTROL_PLANE_URL", "https://evil.test"); expect((await run()).status).toBe(503);
  expect(fetchMock).not.toHaveBeenCalled();
});
it.each([{ ...result(), voice_session_id: "foreign" }, { ...result(), preserved: false }, { ...result(), pending_segments: -1 }, { ...result(), storage_durable: "true" }, { ...result(), marked_at: "2026" }])("rejects malformed/foreign success", async value => {
  fetchMock.mockResolvedValue(Response.json(value)); expect((await run()).status).toBe(503);
});
it("whitelists response and keeps uncertain/missing/source-conflict outcomes explicit", async () => {
  fetchMock.mockResolvedValue(Response.json({ ...result(), actor_id: "private-actor", owner_id: "private-owner", object_key: "private-key" }));
  const text = await (await run()).text(); expect(text).not.toMatch(/private-/);
  for (const status of [404, 409, 503]) {
    fetchMock.mockResolvedValue(Response.json({ error: "private-error" }, { status }));
    const response = await run(); expect(response.status).toBe(status); expect(await response.text()).not.toContain("private-error");
  }
});
