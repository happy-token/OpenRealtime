import { NextRequest, NextResponse } from "next/server";
import { currentAppAdmin } from "@/lib/admin-server";
import { isDiagnosticSessionId, verifyDiagnosticsAccess } from "@/lib/diagnostics-access";
import { parseInputEvidencePage, validEvidenceSequence } from "@/lib/session-input-evidence";
import type { SessionDiagnosticsReport } from "@/lib/session-diagnostics-report";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const authorization = request.headers.get("authorization");
  const machineRequest = authorization !== null;
  if (machineRequest) {
    const token = /^Bearer (\S+)$/i.exec(authorization)?.[1];
    if (!token || !verifyDiagnosticsAccess(token, sessionId, process.env.OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET))
      return NextResponse.json({ error: "未授权" }, { status: 403, headers: { "Cache-Control": "no-store" } });
  } else {
    try {
      if (!await currentAppAdmin(request)) return NextResponse.json({ error: "未授权" }, { status: 403 });
    } catch { return NextResponse.json({ error: "管理员权限服务暂时不可用" }, { status: 503 }); }
  }
  if (!isDiagnosticSessionId(sessionId)) return NextResponse.json({ error: "Session ID 无效" }, { status: 400 });
  const base = process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";
  const names = ["telemetry", "conversation", "debug_log", "input_evidence"] as const;
  const telemetryCursor = request.nextUrl.searchParams.get("telemetry_cursor");
  const debugCursor = request.nextUrl.searchParams.get("debug_cursor");
  const conversationCursor = request.nextUrl.searchParams.get("conversation_cursor");
  const inputCursor = request.nextUrl.searchParams.get("input_cursor");
  if (request.nextUrl.searchParams.getAll("input_cursor").length > 1 || (inputCursor !== null && !validEvidenceSequence(inputCursor))) return NextResponse.json({ error: "输入证据游标无效" }, { status: 400 });
  const validSequence = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= BigInt("9223372036854775807");
  if (request.nextUrl.searchParams.getAll("conversation_cursor").length > 1 || (conversationCursor !== null && !validSequence(conversationCursor))) return NextResponse.json({ error: "对话游标无效" }, { status: 400 });
  if ([telemetryCursor, debugCursor].some(cursor => cursor !== null && !/^[A-Za-z0-9._:-]{1,128}$/.test(cursor))) return NextResponse.json({ error: "游标无效" }, { status: 400 });
  const paths = [telemetryCursor ? `?cursor=${encodeURIComponent(telemetryCursor)}` : "", `/conversation-page?limit=200${conversationCursor ? `&after_sequence=${encodeURIComponent(conversationCursor)}` : ""}`, `/debug-log?limit=2000${debugCursor ? `&cursor=${encodeURIComponent(debugCursor)}` : ""}`, `/input-evidence?limit=100${inputCursor ? `&after_sequence=${encodeURIComponent(inputCursor)}` : ""}`];
  const responses = await Promise.allSettled(paths.map(async (path, index) => {
    const response = await fetch(new URL(`/observability/sessions/${encodeURIComponent(sessionId)}${path}`, base), { cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!response.ok) throw new Error(response.status === 404 ? "not-found" : "unavailable");
    const body = await response.json();
    if (index === 3) return parseInputEvidencePage(body, sessionId, inputCursor ?? "0");
    const valid = index === 0 ? body && body.summary && Array.isArray(body.events) : index === 1 ? body && body.voice_session_id === sessionId && Array.isArray(body.items) && body.items.length <= 200 : body && Array.isArray(body.entries);
    if (!valid) throw new Error("unavailable");
    if (index === 1) {
      let previous = BigInt(conversationCursor ?? "0");
      for (const item of body.items) {
        if (!item || item.voice_session_id !== sessionId || !validSequence(item.journal_sequence)
          || BigInt(item.journal_sequence) <= previous || typeof item.item_id !== "string"
          || typeof item.text !== "string" || !Number.isSafeInteger(item.generation) || item.generation < 0
          || !["user", "assistant"].includes(item.role) || typeof item.status !== "string"
          || typeof item.occurred_at !== "string" || !Number.isFinite(Date.parse(item.occurred_at))) throw new Error("unavailable");
        previous = BigInt(item.journal_sequence);
      }
      if (body.next_cursor !== null && (!validSequence(body.next_cursor)
        || BigInt(body.next_cursor) <= BigInt(conversationCursor ?? "0") || BigInt(body.next_cursor) < previous)) throw new Error("unavailable");
    }
    if (machineRequest) {
      const scoped = index === 0
        ? body.summary.voice_session_id === sessionId && body.events.every((event: { voice_session_id?: string } | null) => event?.voice_session_id === sessionId)
        : index === 1 ? body.items.every((item: { voice_session_id?: string } | null) => item?.voice_session_id === sessionId)
          : body.voice_session_id === sessionId && body.entries.every((entry: { voice_session_id?: string } | null) => entry?.voice_session_id === sessionId);
      if (!scoped) throw new Error("unavailable");
    }
    return body;
  }));
  const report: SessionDiagnosticsReport = { schema_version: 1, session_id: sessionId, telemetry: null, conversation: [], conversation_next_cursor: null, debug_log: null, input_evidence: null, sources: {} as SessionDiagnosticsReport["sources"], audio: { status: "not-queried", catalog_url: `/api/observability/sessions/${encodeURIComponent(sessionId)}/recordings` } };
  responses.forEach((result, index) => {
    const name = names[index];
    if (result.status === "fulfilled") {
      report.sources[name] = { status: "available", truncated: "next_cursor" in result.value ? Boolean(result.value.next_cursor) : name === "telemetry" ? result.value.events?.length >= 5000 : result.value.entries?.length >= 2000 };
      if (name === "telemetry") report.telemetry = result.value;
      else if (name === "conversation") { report.conversation = result.value.items; report.conversation_next_cursor = result.value.next_cursor; }
      else if (name === "debug_log") report.debug_log = result.value;
      else report.input_evidence = result.value;
    } else report.sources[name] = { status: result.reason?.message === "not-found" ? "not-found" : "unavailable", truncated: false, error: "数据源不可用或没有记录" };
  });
  try {
    if (machineRequest) {
      // Global collection health is outside a single-session grant.
      report.collection_health = null;
    } else {
      const health = await fetch(new URL("/observability/health", base), { cache: "no-store", signal: AbortSignal.timeout(3000) });
      const body = health.ok ? await health.json() : null;
      report.collection_health = body?.telemetry && body?.debug_log ? body : null;
    }
  } catch { report.collection_health = null; }
  const hasContent = Boolean(report.input_evidence?.status === "available" || report.telemetry || report.conversation.length || report.conversation_next_cursor || report.debug_log?.entries.length || report.debug_log?.next_cursor || report.input_evidence?.records.length || report.input_evidence?.next_cursor);
  if (!hasContent && report.sources.telemetry.status === "not-found" && !names.some(name => report.sources[name]?.status === "unavailable")) return NextResponse.json({ ...report, error: "未找到该会话" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  const available = names.some(name => report.sources[name]?.status === "available");
  const status = available ? 200 : names.every(name => report.sources[name]?.status === "not-found") ? 404 : 503;
  return NextResponse.json(report, { status, headers: { "Cache-Control": "no-store" } });
}
