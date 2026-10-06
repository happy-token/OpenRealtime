import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET, DELETE } from "./route";
const authorize = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-server", () => ({
  currentAppAdmin: authorize,
  currentAdmin: async () => null, isAdminConfigured: () => true,
}));
beforeEach(() => { authorize.mockReset(); });
afterEach(() => vi.unstubAllGlobals());
it("returns JSON 503 for GET and DELETE when the authorization store fails", async () => {
  authorize.mockRejectedValue(new Error("database unavailable"));
  const context = { params: Promise.resolve({ path: ["sessions"] }) };
  for (const handler of [GET, DELETE]) {
    const response = await handler(new NextRequest("https://app.example/api/observability/sessions"), context);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "管理员权限服务暂时不可用" });
  }
});

it.each(["overview", "sessions"])("explains an unreachable backend for %s without exposing its URL", async path => {
  authorize.mockResolvedValue({ userId: "admin" });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
  const response = await GET(new NextRequest(`https://app.example/api/observability/${path}`), { params: Promise.resolve({ path: [path] }) });
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ error: "诊断服务暂时不可用，请检查语音后端服务后重试" });
});

it.each(["overview", "sessions"])("proxies %s data and query parameters after the backend recovers", async path => {
  authorize.mockResolvedValue({ userId: "admin" });
  const body = path === "overview" ? { session_count: 7, metrics: [] } : [{ voice_session_id: "session-1" }];
  const fetchMock = vi.fn().mockResolvedValue(Response.json(body));
  vi.stubGlobal("fetch", fetchMock);
  const response = await GET(new NextRequest(`https://app.example/api/observability/${path}?minutes=1440`), { params: Promise.resolve({ path: [path] }) });
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual(body);
  const [target] = fetchMock.mock.calls[0];
  expect(target.pathname).toBe(`/observability/${path}`);
  expect(target.search).toBe("?minutes=1440");
});

it("does not query the backend when the application login is missing", async () => {
  authorize.mockResolvedValue(null);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const response = await GET(new NextRequest("https://app.example/api/observability/sessions"), { params: Promise.resolve({ path: ["sessions"] }) });
  expect(response.status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("proxies paginated input evidence for an administrator", async () => {
  authorize.mockResolvedValue({ userId: "admin" });
  const payload = { records: [{ sequence: 13 }], next_sequence: 13, has_more: true };
  const fetchMock = vi.fn().mockResolvedValue(Response.json(payload));
  vi.stubGlobal("fetch", fetchMock);
  const response = await GET(new NextRequest("https://app.example/api/observability/sessions/s1/input-evidence?after_sequence=12&limit=3"), { params: Promise.resolve({ path: ["sessions", "s1", "input-evidence"] }) });
  expect(await response.json()).toEqual(payload);
  expect(fetchMock.mock.calls[0][0].pathname).toBe("/observability/sessions/s1/input-evidence");
  expect(fetchMock.mock.calls[0][0].search).toBe("?after_sequence=12&limit=3");
});

it("denies input evidence without administrator authorization", async () => {
  authorize.mockResolvedValue(null);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const response = await GET(new NextRequest("https://app.example/api/observability/sessions/s1/input-evidence"), { params: Promise.resolve({ path: ["sessions", "s1", "input-evidence"] }) });
  expect(response.status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
});
