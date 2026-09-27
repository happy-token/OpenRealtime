import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor } from "@/lib/provider-instance-access";
import { parseBuiltinProvider, parseProviderCapability } from "@/lib/provider-instances";
import { loadPlatformProviderKey } from "@/lib/platform-provider-credentials";
import { testStreamingLlmInstance } from "@/lib/provider-credential-test";
import { testProviderContract } from "@/lib/provider-contract-test";
import { listPlatformProviderCredentials } from "@/lib/platform-provider-credentials";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userDatabase, userTable } from "@/lib/user-db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (value: object, status = 200) => NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  try {
    if (!await providerActor(request)) return json({ error: "请先登录" }, 401);
    let body: unknown;
    try { body = await readLimitedJson(request, 512); }
    catch (error) { return json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, error instanceof RequestBodyTooLarge ? 413 : 400); }
    const input = body && typeof body === "object" ? body as Record<string, unknown> : {};
    const capability = parseProviderCapability(input.capability);
    const provider = capability && parseBuiltinProvider(input.provider, capability);
    if (!capability || !provider) return json({ error: "供应商配置无效" }, 400);
    const key = loadPlatformProviderKey(capability, provider);
    if (!key) return json({ error: "平台尚未配置该供应商" }, 404);
    const claim = await userDatabase().query(
      `INSERT INTO ${userTable("provider_preview_test_limits")} (scope, issuer, subject, last_started_at)
       VALUES ('platform', '', $1, now())
       ON CONFLICT (scope, issuer, subject) DO UPDATE SET last_started_at = now()
       WHERE ${userTable("provider_preview_test_limits")}.last_started_at < now() - interval '60 seconds'
       RETURNING scope`, [`${capability}:${provider}`]);
    if (!claim.rowCount) return json({ error: "平台测试过于频繁，请 60 秒后重试" }, 429);
    const result = capability === "llm"
      ? await testStreamingLlmInstance(provider as "deepseek" | "openai", key, "")
      : capability === "asr" && provider === "dashscope"
        ? await testProviderContract("asr", "dashscope", key,
            listPlatformProviderCredentials().find((item) => item.capability === capability && item.provider === provider)?.baseUrl)
        : await testProviderContract(capability, provider as "doubao" | "dashscope", key);
    return json(result);
  } catch { return json({ error: "平台供应商测试暂不可用" }, 503); }
}
