import type { BuiltinProvider, ProviderCapability } from "./provider-instances";

export type ProviderPreset = { id: BuiltinProvider; name: string; baseUrl: string; keyUrl: string; intro: string };

export const PROVIDER_CATALOG: Record<ProviderCapability, ProviderPreset[]> = {
  asr: [
    { id: "doubao", name: "豆包 ASR", baseUrl: "https://openspeech.bytedance.com", keyUrl: "https://console.volcengine.com/speech/new/setting/apikeys?projectName=default", intro: "流式语音识别，持续返回中间文本与最终文本。" },
    { id: "dashscope", name: "阿里云百炼 ASR", baseUrl: "https://dashscope.aliyuncs.com", keyUrl: "https://help.aliyun.com/zh/model-studio/get-api-key", intro: "Qwen-ASR-Realtime 流式识别；推荐将 Base URL 改为包含 Workspace ID 的工作空间专属域名。" },
  ],
  tts: [
    { id: "doubao", name: "豆包 TTS", baseUrl: "https://openspeech.bytedance.com", keyUrl: "https://console.volcengine.com/speech/new/setting/apikeys?projectName=default", intro: "双流式语音合成，支持持续输入文本与流式输出音频。" },
    { id: "dashscope", name: "阿里云百炼 TTS", baseUrl: "https://dashscope.aliyuncs.com", keyUrl: "https://help.aliyun.com/zh/model-studio/get-api-key", intro: "百炼语音合成服务，使用百炼 API Key。" },
  ],
  llm: [
    { id: "deepseek", name: "DeepSeek", baseUrl: "https://api.deepseek.com", keyUrl: "https://platform.deepseek.com/api_keys", intro: "支持流式文本输出的对话模型。" },
    { id: "openai", name: "OpenAI", baseUrl: "https://api.openai.com/v1", keyUrl: "https://platform.openai.com/api-keys", intro: "支持流式文本输出的对话模型。" },
  ],
};

/** Built-in bridges may contact only their known official origin and protocol path. */
export function normalizeProviderBaseUrl(capability: ProviderCapability, provider: BuiltinProvider, input: string): string | null {
  const preset = PROVIDER_CATALOG[capability].find((item) => item.id === provider);
  if (!preset || input.length > 220) return null;
  try {
    const url = new URL(input);
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash) return null;
    const path = url.pathname.replace(/\/+$/, "") || "";
    if (provider === "deepseek") return url.hostname === "api.deepseek.com" && (path === "" || path === "/v1")
      ? `https://api.deepseek.com${path}` : null;
    if (provider === "openai") return url.hostname === "api.openai.com" && path === "/v1"
      ? "https://api.openai.com/v1" : null;
    if (provider === "doubao") return url.hostname === "openspeech.bytedance.com" && path === ""
      ? "https://openspeech.bytedance.com" : null;
    if (provider === "dashscope" && path === "") {
      const host = url.hostname;
      if (host === "dashscope.aliyuncs.com" || host === "dashscope-intl.aliyuncs.com"
        || /^[a-z0-9][a-z0-9-]{1,127}\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com$/.test(host)) {
        return `https://${host}`;
      }
    }
    return null;
  } catch { return null; }
}
