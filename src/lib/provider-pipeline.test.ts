import { expect, it } from "vitest";
import { providerPipelineFallbacks } from "./provider-pipeline";

it("describes the same legacy voice defaults without exposing API keys", () => {
  const platform = [
    { capability: "asr" as const, provider: "doubao" as const, name: "豆包 ASR", keySuffix: "asr1" },
    { capability: "tts" as const, provider: "dashscope" as const, name: "百炼 TTS", keySuffix: "tts2" },
    { capability: "llm" as const, provider: "deepseek" as const, name: "DeepSeek", keySuffix: "llm3" },
  ];
  const result = providerPipelineFallbacks([], platform, { VOICEAGENT_TTS_BACKEND: "bailian" });
  expect(result.asr).toMatchObject({ scope: "platform", name: "豆包 ASR", keySuffix: "asr1" });
  expect(result.tts).toMatchObject({ scope: "platform", name: "百炼 TTS", keySuffix: "tts2" });
  expect(result.llm).toMatchObject({ scope: "platform", name: "DeepSeek", keySuffix: "llm3" });
});
