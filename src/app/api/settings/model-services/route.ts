import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE, adminAuthConfigFromEnv, verifyAdminSessionToken } from "@/lib/admin-auth";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import {
  isModelServiceKind, modelServiceConnections, normalizeModelServiceToken,
  normalizeModelServiceUrl, saveModelServiceConnection,
} from "@/lib/model-service-connections";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

function authorized(request: NextRequest): boolean {
  const config = adminAuthConfigFromEnv();
  return Boolean(config && verifyAdminSessionToken(request.cookies.get(ADMIN_SESSION_COOKIE)?.value, config));
}

export async function GET(request: NextRequest) {
  if (!authorized(request)) return json({ error: "请先以管理员身份登录" }, 401);
  try {
    const connections = await modelServiceConnections();
    return json({ services: Object.fromEntries(Object.entries(connections).map(([kind, value]) => [kind, {
      url: value.url, tokenConfigured: Boolean(value.token),
    }])) });
  } catch {
    return json({ error: "读取服务配置失败" }, 503);
  }
}

export async function PATCH(request: NextRequest) {
  if (!authorized(request)) return json({ error: "请先以管理员身份登录" }, 401);
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  let body: { kind?: unknown; url?: unknown; token?: unknown };
  try {
    body = await readLimitedJson(request, 4096) as typeof body;
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    return json({ error: "请求内容无效" }, 400);
  }
  if (!isModelServiceKind(body?.kind)) return json({ error: "未知的模型服务" }, 400);
  let url: string;
  let token: string | undefined;
  try {
    url = normalizeModelServiceUrl(body.url);
    token = body.token === undefined ? undefined : normalizeModelServiceToken(body.token);
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "配置格式无效" }, 400);
  }
  try {
    const saved = await saveModelServiceConnection(body.kind, { url, token });
    return json({ kind: body.kind, url: saved.url, tokenConfigured: Boolean(saved.token) });
  } catch {
    return json({ error: "保存服务配置失败" }, 503);
  }
}
