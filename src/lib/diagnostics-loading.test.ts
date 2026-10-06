import { afterEach, expect, it, vi } from "vitest";
import { loadDiagnosticsOverview } from "./observability";

const unavailable = "诊断服务暂时不可用，请检查语音后端服务后重试";
const overview = { session_count: 7, metrics: [] };
const sessions = [{ voice_session_id: "session-1" }];
const health = { status: "ok", telemetry: { dropped_events: 0 }, debug_log: { dropped_events: 0 } };

afterEach(() => vi.unstubAllGlobals());

function responses(aggregate: Response, list: Response, collection = Response.json(health)) {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(aggregate)
    .mockResolvedValueOnce(list)
    .mockResolvedValueOnce(collection);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("loads real API shapes for both overview and sessions with one abort boundary", async () => {
  const fetchMock = responses(Response.json(overview), Response.json(sessions));
  const signal = new AbortController().signal;
  expect(await loadDiagnosticsOverview(1440, signal)).toEqual({ overview, sessions, health, errors: [] });
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    "/api/observability/overview?minutes=1440",
    "/api/observability/sessions?minutes=1440&limit=500",
    "/api/observability/health",
  ]);
  for (const [, options] of fetchMock.mock.calls) expect(options).toEqual({ cache: "no-store", signal });
});

it("shows the backend failure reason for both unavailable data sources", async () => {
  responses(Response.json({ error: unavailable }, { status: 503 }), Response.json({ error: unavailable }, { status: 503 }));
  const result = await loadDiagnosticsOverview(1440, new AbortController().signal);
  expect(result.overview).toBeNull();
  expect(result.sessions).toEqual([]);
  expect(result.errors).toEqual([`总览指标暂时不可用：${unavailable}`, `会话列表暂时不可用：${unavailable}`]);
});

it("keeps available overview data when only session loading fails", async () => {
  responses(Response.json(overview), Response.json({ error: "诊断查询超时" }, { status: 504 }));
  const result = await loadDiagnosticsOverview(60, new AbortController().signal);
  expect(result.overview).toEqual(overview);
  expect(result.sessions).toEqual([]);
  expect(result.errors).toEqual(["会话列表暂时不可用：诊断查询超时"]);
});
