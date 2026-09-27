import type { ProviderCapability } from "./provider-instances";
import type { PlatformProviderCredential } from "./platform-provider-credentials";
import type { PersonalKeyStatus } from "./user-provider-credentials";

export type PipelineFallback = { name: string; scope: "personal" | "platform" | "none";
  provider: string; keySuffix?: string };

/** Describe only the legacy default path. Explicit selections override this on the page. */
export function providerPipelineFallbacks(
  personal: PersonalKeyStatus[], platform: PlatformProviderCredential[],
  environment: Record<string, string | undefined> = process.env,
): Record<ProviderCapability, PipelineFallback> {
  const personalKey = (provider: string) => personal.find((entry) => entry.provider === provider && entry.configured);
  const platformKey = (capability: ProviderCapability, provider: string) =>
    platform.find((entry) => entry.capability === capability && entry.provider === provider);
  const speech = (capability: "asr" | "tts", provider: "doubao" | "dashscope"): PipelineFallback => {
    const mine = personalKey(provider);
    if (mine) return { scope: "personal", provider, name: `${provider === "doubao" ? "豆包" : "阿里云百炼"}（旧版个人 Key）`, keySuffix: mine.suffix };
    const shared = platformKey(capability, provider);
    return shared ? { scope: "platform", provider, name: shared.name, keySuffix: shared.keySuffix }
      : { scope: "none", provider, name: "未配置" };
  };
  const personalLlm = personal.filter((entry) => (entry.provider === "deepseek" || entry.provider === "openai") && entry.configured)
    .sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? "") || a.provider.localeCompare(b.provider))[0];
  let llm: PipelineFallback;
  if (personalLlm) {
    llm = { scope: "personal", provider: personalLlm.provider,
      name: `${personalLlm.provider === "deepseek" ? "DeepSeek" : "OpenAI"}（旧版个人 Key）`, keySuffix: personalLlm.suffix };
  } else if (environment.VOICEAGENT_LLM_API_KEY?.trim()) {
    llm = { scope: "platform", provider: "custom", name: "自定义 LLM（平台）",
      keySuffix: environment.VOICEAGENT_LLM_API_KEY.trim().slice(-4) };
  } else {
    const shared = platformKey("llm", "deepseek") ?? platformKey("llm", "openai");
    llm = shared ? { scope: "platform", provider: shared.provider, name: shared.name, keySuffix: shared.keySuffix }
      : environment.API_KEY?.trim() ? { scope: "platform", provider: "bella", name: "旧版平台 LLM",
        keySuffix: environment.API_KEY.trim().slice(-4) } : { scope: "none", provider: "", name: "未配置" };
  }
  return {
    asr: speech("asr", "doubao"),
    llm,
    tts: speech("tts", environment.VOICEAGENT_TTS_BACKEND === "bailian" ? "dashscope" : "doubao"),
  };
}
