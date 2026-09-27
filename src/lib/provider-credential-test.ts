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
      if (!response.body) return { ok: false, message: "服务未返回可用音频" };
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let body = "";
      let bytes = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          bytes += value.byteLength;
          if (bytes > 262_144) return { ok: false, message: "语音测试响应过大" };
          body += decoder.decode(value, { stream: true });
        }
      } finally { await reader.cancel().catch(() => {}); }
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

const STREAMING_LLM = {
  deepseek: { endpoint: "https://api.deepseek.com/chat/completions", defaultModel: "deepseek-chat" },
  openai: { endpoint: "https://api.openai.com/v1/chat/completions", defaultModel: "gpt-4.1-mini" },
} as const;

/** Probe actual incremental text at a fixed vendor endpoint; never return the generated text. */
export async function testStreamingLlmInstance(
  provider: "deepseek" | "openai", apiKey: string, model: string,
  fetchImpl: typeof fetch = fetch,
  baseUrl = provider === "deepseek" ? "https://api.deepseek.com" : "https://api.openai.com/v1",
): Promise<{ ok: boolean; message: string; firstTextMs?: number }> {
  const config = STREAMING_LLM[provider];
  const started = performance.now();
  try {
    const response = await fetchImpl(`${baseUrl}/chat/completions`, {
      method: "POST", headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: model || config.defaultModel, stream: true, max_tokens: 24,
        messages: [{ role: "user", content: "请用两句话简短问好。" }] }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15_000),
    });
    if (!response.ok) return { ok: false, message: `流式测试未通过（服务返回 ${response.status}）` };
    if (!response.body) return { ok: false, message: "服务未返回流式响应" };
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let totalBytes = 0;
    let textChunks = 0;
    let firstTextMs: number | undefined;
    try {
      while (textChunks < 2) {
        const { done, value } = await reader.read();
        if (done) break;
        totalBytes += value.byteLength;
        if (totalBytes > 65_536) return { ok: false, message: "流式测试响应过大" };
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") break;
          try {
            const payload = JSON.parse(data) as { choices?: { delta?: { content?: unknown } }[] };
            const content = payload.choices?.[0]?.delta?.content;
            if (typeof content === "string" && content.trim()) {
              if (firstTextMs === undefined) firstTextMs = Math.max(0, performance.now() - started);
              textChunks++;
            }
          } catch { /* Ignore SSE keepalives and provider metadata. */ }
        }
      }
    } finally { await reader.cancel().catch(() => {}); }
    return textChunks >= 2 ? { ok: true, message: `流式文本正常，首字 ${Math.round(firstTextMs ?? 0)} ms`, firstTextMs }
      : { ok: false, message: "服务已响应，但未返回连续的流式文本" };
  } catch { return { ok: false, message: "流式请求失败，请检查模型、凭证或网络" }; }
}
