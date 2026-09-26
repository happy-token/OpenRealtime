import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE, adminAuthConfigFromEnv, verifyAdminSessionToken } from "@/lib/admin-auth";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { isModelServiceKind, modelServiceConnection, normalizeModelServiceToken, normalizeModelServiceUrl, probeModelService } from "@/lib/model-service-connections";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const config = adminAuthConfigFromEnv();
  if (!config || !verifyAdminSessionToken(request.cookies.get(ADMIN_SESSION_COOKIE)?.value, config)) {
    return NextResponse.json({ error: "请先以管理员身份登录" }, { status: 401 });
  }
  if (!isSameOriginAvatarMutation(request)) return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  try {
    const body = await readLimitedJson(request, 4096) as { kind?: unknown; url?: unknown; token?: unknown };
    if (!isModelServiceKind(body?.kind)) return NextResponse.json({ error: "未知的模型服务" }, { status: 400 });
    const saved = await modelServiceConnection(body.kind);
    const url = body.url === undefined ? saved.url : normalizeModelServiceUrl(body.url);
    const token = body.token === undefined ? (url === saved.url ? saved.token : "") : normalizeModelServiceToken(body.token);
    const result = await probeModelService(body.kind, { url, token });
    return NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return NextResponse.json({ error: "请求内容过大" }, { status: 413 });
    return NextResponse.json({ error: error instanceof Error ? error.message : "连接测试失败" }, { status: 400 });
  }
}
