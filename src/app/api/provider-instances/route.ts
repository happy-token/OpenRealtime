import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor } from "@/lib/provider-instance-access";
import { createProviderInstance, listProviderInstances, ProviderInstanceQuotaError, validateProviderInstanceInput } from "@/lib/provider-instances";
import { listPlatformProviderCredentials } from "@/lib/platform-provider-credentials";
import { providerPipelineFallbacks } from "@/lib/provider-pipeline";
import { listPersonalKeyStatuses } from "@/lib/user-provider-credentials";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const json = (value: object, status = 200) => NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });

export async function GET(request: NextRequest) {
  try {
    const actor = await providerActor(request);
    if (!actor) return json({ error: "请先登录" }, 401);
    const platformCredentials = listPlatformProviderCredentials();
    return json({ ...await listProviderInstances(actor.user, actor.admin),
      platformCredentials,
      pipelineFallbacks: providerPipelineFallbacks(actor.signedIn ? await listPersonalKeyStatuses(actor.user) : [], platformCredentials),
      signedIn: actor.signedIn, admin: actor.admin });
  } catch { return json({ error: "供应商实例暂不可用" }, 503); }
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  try {
    const actor = await providerActor(request);
    if (!actor) return json({ error: "请先登录" }, 401);
    let body: unknown;
    try { body = await readLimitedJson(request, 2048); }
    catch (error) { return json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, error instanceof RequestBodyTooLarge ? 413 : 400); }
    const input = validateProviderInstanceInput(body);
    const scope = body && typeof body === "object" && "scope" in body ? body.scope : "personal";
    if (!input || (scope !== "personal" && scope !== "platform")) return json({ error: "供应商配置无效" }, 400);
    if (scope === "platform" && !actor.admin) return json({ error: "无权配置平台供应商" }, 403);
    if (scope === "personal" && !actor.signedIn) return json({ error: "请先登录用户账号" }, 401);
    const instance = await createProviderInstance(actor.user, scope, input);
    return json({ instance }, 201);
  } catch (error) {
    return error instanceof ProviderInstanceQuotaError ? json({ error: error.message }, 429)
      : json({ error: "创建供应商实例失败" }, 503);
  }
}
