import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor } from "@/lib/provider-instance-access";
import { validateProviderInstanceInput } from "@/lib/provider-instances";
import { testStreamingLlmInstance } from "@/lib/provider-credential-test";
import { testProviderContract } from "@/lib/provider-contract-test";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userDatabase, userTable } from "@/lib/user-db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (value: object, status = 200) => NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });

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
    if (!input || !input.apiKey || (scope !== "personal" && scope !== "platform")) return json({ error: "供应商配置无效" }, 400);
    if (scope === "platform" && !actor.admin) return json({ error: "无权测试平台供应商" }, 403);
    if (scope === "personal" && !actor.signedIn) return json({ error: "请先登录用户账号" }, 401);
    const issuer = scope === "platform" ? "" : actor.user.issuer;
    const subject = scope === "platform" ? "" : actor.user.subject;
    const claim = await userDatabase().query(
      `INSERT INTO ${userTable("provider_preview_test_limits")} (scope, issuer, subject, last_started_at)
       VALUES ($1, $2, $3, now())
       ON CONFLICT (scope, issuer, subject) DO UPDATE SET last_started_at = now()
       WHERE ${userTable("provider_preview_test_limits")}.last_started_at < now() - interval '60 seconds'
       RETURNING scope`, [scope, issuer, subject]);
    if (!claim.rowCount) return json({ error: "预检过于频繁，请 60 秒后重试" }, 429);
    const result = input.capability === "llm"
      ? await testStreamingLlmInstance(input.provider as "deepseek" | "openai", input.apiKey, input.model, fetch, input.baseUrl)
      : input.capability === "asr" && input.provider === "dashscope"
        ? await testProviderContract("asr", "dashscope", input.apiKey, input.baseUrl, input.model)
        : await testProviderContract(input.capability, input.provider as "doubao" | "dashscope", input.apiKey);
    return json(result);
  } catch { return json({ error: "供应商预检暂不可用" }, 503); }
}
