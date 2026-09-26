import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { isTestableProvider, testProviderCredential } from "@/lib/provider-credential-test";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { loadPersonalKey, parsePersonalKeyProvider } from "@/lib/user-provider-credentials";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  try {
    const user = await userFromRequest(request);
    if (!user) return json({ error: "请先登录" }, 401);
    let body: { provider?: unknown; apiKey?: unknown };
    try { body = await readLimitedJson(request, 2048) as typeof body ?? {}; }
    catch (error) {
      return error instanceof RequestBodyTooLarge
        ? json({ error: "请求内容过大" }, 413)
        : json({ error: "请求内容无效" }, 400);
    }
    const provider = parsePersonalKeyProvider(body.provider);
    if (!provider || !isTestableProvider(provider)) return json({ error: "暂不支持测试该供应商" }, 400);
    if (body.apiKey !== undefined && (typeof body.apiKey !== "string" || body.apiKey.length < 8
      || body.apiKey.length > 512 || body.apiKey !== body.apiKey.trim() || /[\x00-\x1f\x7f]/.test(body.apiKey))) {
      return json({ error: "请填写有效的 API Key" }, 400);
    }
    const key = typeof body.apiKey === "string" ? body.apiKey : await loadPersonalKey(user, provider);
    if (!key) return json({ error: "请先填写并保存 API Key" }, 404);
    return json(await testProviderCredential(provider, key));
  } catch {
    return json({ error: "连接测试暂不可用" }, 503);
  }
}
