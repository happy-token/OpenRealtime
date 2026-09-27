import type { BuiltinProvider, ProviderCapability } from "./provider-instances";

export type PlatformProviderCredential = {
  capability: ProviderCapability;
  provider: BuiltinProvider;
  name: string;
  keySuffix: string;
  baseUrl?: string;
};

const PLATFORM_PROVIDERS: Array<{
  capability: ProviderCapability; provider: BuiltinProvider; name: string; envName: string;
}> = [
  { capability: "asr", provider: "doubao", name: "豆包 ASR", envName: "DOUBAO_API_KEY" },
  { capability: "asr", provider: "dashscope", name: "阿里云百炼 ASR", envName: "DASHSCOPE_API_KEY" },
  { capability: "tts", provider: "doubao", name: "豆包 TTS", envName: "DOUBAO_API_KEY" },
  { capability: "tts", provider: "dashscope", name: "阿里云百炼 TTS", envName: "DASHSCOPE_API_KEY" },
  { capability: "llm", provider: "deepseek", name: "DeepSeek", envName: "DEEPSEEK_API_KEY" },
  { capability: "llm", provider: "openai", name: "OpenAI", envName: "OPENAI_API_KEY" },
];

export function listPlatformProviderCredentials(): PlatformProviderCredential[] {
  return PLATFORM_PROVIDERS.flatMap(({ capability, provider, name, envName }) => {
    const key = process.env[envName]?.trim();
    const workspaceId = process.env.DASHSCOPE_WORKSPACE_ID?.trim();
    const baseUrl = capability === "asr" && provider === "dashscope" && workspaceId && /^[a-z0-9][a-z0-9-]{1,127}$/i.test(workspaceId)
      ? `https://${workspaceId.toLowerCase()}.cn-beijing.maas.aliyuncs.com` : undefined;
    return key ? [{ capability, provider, name, keySuffix: key.slice(-4), ...(baseUrl ? { baseUrl } : {}) }] : [];
  });
}

export function loadPlatformProviderKey(capability: ProviderCapability, provider: BuiltinProvider): string | null {
  const entry = PLATFORM_PROVIDERS.find((item) => item.capability === capability && item.provider === provider);
  return entry ? process.env[entry.envName]?.trim() || null : null;
}
