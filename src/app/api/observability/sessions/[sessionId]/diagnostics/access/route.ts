import { NextRequest, NextResponse } from "next/server";
import { currentAppAdmin } from "@/lib/admin-server";
import { isSameOriginRequest } from "@/lib/request-origin";
import { isDiagnosticSessionId, issueDiagnosticsAccess } from "@/lib/diagnostics-access";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" };

/** Only the signed-in admin can delegate one short read grant to a named Agent. */
export async function POST(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  try {
    if (!await currentAppAdmin(request)) return NextResponse.json({ error: "未授权" }, { status: 403, headers });
  } catch { return NextResponse.json({ error: "管理员权限服务暂时不可用" }, { status: 503, headers }); }
  if (!isSameOriginRequest(request))
    return NextResponse.json({ error: "请求来源无效" }, { status: 403, headers });
  const { sessionId } = await context.params;
  const agentId = request.nextUrl.searchParams.get("agent_id") ?? "diagnostic-agent";
  if (!isDiagnosticSessionId(sessionId) || !/^[A-Za-z0-9._:-]{1,64}$/.test(agentId))
    return NextResponse.json({ error: "Session ID 或 Agent ID 无效" }, { status: 400, headers });
  try {
    const grant = issueDiagnosticsAccess(sessionId, agentId, process.env.OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET);
    return NextResponse.json(grant, { status: 201, headers });
  } catch { return NextResponse.json({ error: "Agent 诊断授权尚未配置" }, { status: 503, headers }); }
}
