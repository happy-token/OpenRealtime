import { NextRequest, NextResponse } from "next/server";
import { currentAppAdmin } from "@/lib/admin-server";
import type { SessionDiagnosticsReport } from "@/lib/session-diagnostics-report";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  try {
    if (!await currentAppAdmin(request)) return NextResponse.json({ error: "未授权" }, { status: 403 });
  } catch { return NextResponse.json({ error: "管理员权限服务暂时不可用" }, { status: 503 }); }
  const { sessionId } = await context.params;
  if (!/^[A-Za-z0-9._:-]{1,128}$/.test(sessionId)) return NextResponse.json({ error: "Session ID 无效" }, { status: 400 });
  const base = process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";
  const names = ["telemetry", "conversation", "debug_log"] as const;
  const telemetryCursor = request.nextUrl.searchParams.get("telemetry_cursor");
  const debugCursor = request.nextUrl.searchParams.get("debug_cursor");
  if ([telemetryCursor, debugCursor].some(cursor => cursor !== null && !/^[A-Za-z0-9._:-]{1,128}$/.test(cursor))) return NextResponse.json({ error: "游标无效" }, { status: 400 });
  const paths = [telemetryCursor ? `?cursor=${encodeURIComponent(telemetryCursor)}` : "", "/conversation", `/debug-log?limit=2000${debugCursor ? `&cursor=${encodeURIComponent(debugCursor)}` : ""}`];
  const responses = await Promise.allSettled(paths.map(async (path, index) => {
    const response = await fetch(new URL(`/observability/sessions/${encodeURIComponent(sessionId)}${path}`, base), { cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!response.ok) throw new Error(response.status === 404 ? "not-found" : "unavailable");
    const body = await response.json();
    const valid = index === 0 ? body && body.summary && Array.isArray(body.events) : index === 1 ? Array.isArray(body) : body && Array.isArray(body.entries);
    if (!valid) throw new Error("unavailable");
    return body;
  }));
  const report: SessionDiagnosticsReport = { schema_version: 1, session_id: sessionId, telemetry: null, conversation: [], debug_log: null, sources: {} as SessionDiagnosticsReport["sources"], audio: { status: "not-configured" } };
  responses.forEach((result, index) => {
    const name = names[index];
    if (result.status === "fulfilled") {
      report.sources[name] = { status: "available", truncated: name === "conversation" ? false : "next_cursor" in result.value ? Boolean(result.value.next_cursor) : name === "telemetry" ? result.value.events?.length >= 5000 : result.value.entries?.length >= 2000 };
      if (name === "telemetry") report.telemetry = result.value;
      else if (name === "conversation") report.conversation = result.value;
      else report.debug_log = result.value;
    } else report.sources[name] = { status: result.reason?.message === "not-found" ? "not-found" : "unavailable", truncated: false, error: "数据源不可用或没有记录" };
  });
  try {
    const health = await fetch(new URL("/observability/health", base), { cache: "no-store", signal: AbortSignal.timeout(3000) });
    const body = health.ok ? await health.json() : null;
    report.collection_health = body?.telemetry && body?.debug_log ? body : null;
  } catch { report.collection_health = null; }
  const hasContent = Boolean(report.telemetry || report.conversation.length || report.debug_log?.entries.length);
  if (!hasContent && report.sources.telemetry.status === "not-found" && !names.some(name => report.sources[name].status === "unavailable")) return NextResponse.json({ ...report, error: "未找到该会话" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  const available = names.some(name => report.sources[name].status === "available");
  const status = available ? 200 : names.every(name => report.sources[name].status === "not-found") ? 404 : 503;
  return NextResponse.json(report, { status, headers: { "Cache-Control": "no-store" } });
}
