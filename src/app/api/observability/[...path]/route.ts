import { NextRequest, NextResponse } from "next/server";
import { currentAppAdmin } from "@/lib/admin-server";

const CONTROL_PLANE_URL =
  process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";

async function authorizationError(request: NextRequest): Promise<NextResponse | null> {
  try {
    if (await currentAppAdmin(request)) return null;
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  } catch {
    return NextResponse.json({ error: "管理员权限服务暂时不可用" }, { status: 503 });
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const denied = await authorizationError(request);
  if (denied) return denied;
  const { path } = await context.params;
  if (!path.length || path.some((part) => part.length > 128)) {
    return NextResponse.json({ error: "无效的诊断路径" }, { status: 400 });
  }
  const target = new URL(
    `/observability/${path.map(encodeURIComponent).join("/")}`,
    CONTROL_PLANE_URL,
  );
  target.search = request.nextUrl.search;

  try {
    const response = await fetch(target, { cache: "no-store", signal: AbortSignal.timeout(10_000) });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return NextResponse.json(
      { error: "诊断服务暂时不可用" },
      { status: 503 },
    );
  }
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const denied = await authorizationError(request);
  if (denied) return denied;
  const origin = request.headers.get("origin");
  if (origin !== request.nextUrl.origin) {
    return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  }
  const { path } = await context.params;
  if (path.length !== 1 || path[0] !== "sessions") {
    return NextResponse.json({ error: "无效的诊断路径" }, { status: 400 });
  }
  let payload: { session_ids?: unknown };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "请求格式错误" }, { status: 400 });
  }
  const sessionIds = payload.session_ids;
  const validSessionId = /^[A-Za-z0-9._:-]{1,128}$/;
  if (
    !Array.isArray(sessionIds) ||
    !sessionIds.length ||
    sessionIds.length > 100 ||
    !sessionIds.every((sessionId) => typeof sessionId === "string" && validSessionId.test(sessionId)) ||
    new Set(sessionIds).size !== sessionIds.length
  ) {
    return NextResponse.json({ error: "会话 ID 列表无效" }, { status: 400 });
  }
  const target = new URL("/observability/sessions", CONTROL_PLANE_URL);
  try {
    const response = await fetch(target, {
      method: "DELETE",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_ids: sessionIds }),
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch {
    return NextResponse.json(
      { error: "诊断服务暂时不可用" },
      { status: 503 },
    );
  }
}
