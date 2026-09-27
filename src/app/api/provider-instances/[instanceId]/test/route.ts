import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor, validInstanceId } from "@/lib/provider-instance-access";
import { claimProviderConnectionTest, loadProviderInstanceKey, recordProviderConnectionTest } from "@/lib/provider-instances";
import { testStreamingLlmInstance } from "@/lib/provider-credential-test";
import { ProviderContractUnavailableError, testProviderContract } from "@/lib/provider-contract-test";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Params = { params: Promise<{ instanceId: string }> };

export async function POST(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  const { instanceId } = await params;
  if (!validInstanceId(instanceId)) return NextResponse.json({ error: "实例 ID 无效" }, { status: 400 });
  try {
    const actor = await providerActor(request);
    if (!actor) return NextResponse.json({ error: "请先登录" }, { status: 401 });
    const loaded = await loadProviderInstanceKey(actor.user, instanceId, actor.admin);
    if (!loaded) return NextResponse.json({ error: "实例不存在" }, { status: 404 });
    if (!await claimProviderConnectionTest(actor.user, loaded.instance.scope, instanceId, loaded.keyVersion)) {
      return NextResponse.json({ error: "能力测试过于频繁，请 60 秒后重试" }, { status: 429,
        headers: { "Retry-After": "60" } });
    }
    const result = loaded.instance.capability === "llm"
      ? await testStreamingLlmInstance(loaded.instance.provider as "deepseek" | "openai", loaded.key, loaded.instance.model, fetch, loaded.instance.baseUrl)
      : loaded.instance.capability === "asr" && loaded.instance.provider === "dashscope"
        ? await testProviderContract("asr", "dashscope", loaded.key, loaded.instance.baseUrl, loaded.instance.model)
        : await testProviderContract(loaded.instance.capability, loaded.instance.provider as "doubao" | "dashscope", loaded.key);
    const firstOutputMs = "firstOutputMs" in result ? result.firstOutputMs : undefined;
    const message = firstOutputMs === undefined ? result.message
      : `${result.message}；${loaded.instance.capability === "tts" ? "首音" : "首字"} ${Math.round(firstOutputMs)} ms`;
    const stored = await recordProviderConnectionTest(actor.user, loaded.instance.scope, instanceId,
      loaded.keyVersion, result.ok, message);
    return stored ? NextResponse.json({ ...result, message, level: loaded.instance.capability === "llm" ? "streaming" : "contract" })
      : NextResponse.json({ error: "配置已变更，请重新测试" }, { status: 409 });
  } catch (error) { return NextResponse.json({ error: error instanceof ProviderContractUnavailableError
    ? error.message : "能力测试失败" }, { status: 503 }); }
}
