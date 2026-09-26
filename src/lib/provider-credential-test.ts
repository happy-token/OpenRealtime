import { randomUUID } from "node:crypto";
import type { PersonalKeyProvider } from "./user-provider-credentials";

export type TestableProvider = Extract<PersonalKeyProvider, "doubao" | "dashscope" | "deepseek" | "openai">;

export function isTestableProvider(provider: PersonalKeyProvider): provider is TestableProvider {
  return provider === "doubao" || provider === "dashscope" || provider === "deepseek" || provider === "openai";
}

const MODEL_ENDPOINTS: Record<Exclude<TestableProvider, "doubao" | "dashscope">, string> = {
  deepseek: "https://api.deepseek.com/models",
  openai: "https://api.openai.com/v1/models",
};

function dashscopeModelsEndpoint() {
  const workspaceId = process.env.DASHSCOPE_WORKSPACE_ID?.trim();
  return workspaceId && /^[A-Za-z0-9-]+$/.test(workspaceId)
    ? `https://${workspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/models`
    : "https://dashscope.aliyuncs.com/api/v1/models/permissions?authorization_scope=AUTHORIZED&action=INFERENCE&page_no=1&page_size=20";
}

/** A user-initiated vendor request; never include credentials or vendor response bodies in the result. */
export async function testProviderCredential(
  provider: TestableProvider,
  apiKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<{ ok: boolean; message: string }> {
  try {
    if (provider === "doubao") {
      const response = await fetchImpl("https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Api-Key": apiKey,
          "X-Api-Resource-Id": "seed-tts-2.0",
          "X-Api-Request-Id": randomUUID(),
        },
        body: JSON.stringify({
          user: { uid: "openrealtime-key-test" },
          req_params: {
            text: "测试",
            speaker: "zh_female_vv_uranus_bigtts",
            sample_rate: 24000,
            audio_params: { format: "mp3", speech_rate: 0, loudness_rate: 0 },
          },
        }),
        cache: "no-store",
        signal: AbortSignal.timeout(12_000),
      });
      if (!response.ok) return { ok: false, message: `测试未通过（服务返回 ${response.status}）` };
      const body = await response.text();
      let hasAudio = false;
      let vendorError = false;
      for (const line of body.split(/\r?\n/)) {
        if (!line.startsWith("data:")) continue;
        try {
          const event = JSON.parse(line.slice(5)) as { code?: number; data?: unknown };
          if (event.code !== undefined && event.code !== 0 && event.code !== 20000000) vendorError = true;
          if ((event.code === 0 || event.code === 20000000)
            && typeof event.data === "string" && event.data.length > 0) hasAudio = true;
        } catch { /* Ignore non-JSON SSE events. */ }
      }
      return hasAudio && !vendorError
        ? { ok: true, message: "连接成功，语音合成可用" }
        : { ok: false, message: "服务已响应，但未返回可用音频" };
    }

    const response = await fetchImpl(provider === "dashscope" ? dashscopeModelsEndpoint() : MODEL_ENDPOINTS[provider], {
      headers: { Authorization: `Bearer ${apiKey}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return { ok: false, message: `测试未通过（服务返回 ${response.status}）` };
    const payload = await response.json().catch(() => null) as {
      data?: unknown; output?: { models?: unknown; permissions?: unknown }; success?: boolean; code?: unknown;
    } | null;
    return payload?.success !== false && (payload?.code === undefined || payload.code === null)
      && (Array.isArray(payload?.data) || Array.isArray(payload?.output?.models) || Array.isArray(payload?.output?.permissions))
      ? { ok: true, message: "连接成功，可读取模型列表" }
      : { ok: false, message: "服务已响应，但结果格式不符合预期" };
  } catch {
    return { ok: false, message: "连接失败，请检查网络或稍后重试" };
  }
}
