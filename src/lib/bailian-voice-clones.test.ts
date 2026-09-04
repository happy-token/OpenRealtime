import { describe, expect, it, vi } from "vitest";
import {
  deleteBailianClonedVoice,
  listBailianClonedVoices,
  mergeBailianClonedVoiceCatalog,
  resolveBailianCloneEndpoint,
  voiceCloneConfiguration,
} from "./bailian-voice-clones";

describe("Bailian voice clones", () => {
  it("uses the configured workspace endpoint without exposing credentials", () => {
    expect(resolveBailianCloneEndpoint({
      BAILIAN_API_HOST: "https://llm-demo.cn-beijing.maas.aliyuncs.com/custom/path",
    })).toBe("https://llm-demo.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization");
  });

  it("reports every server-side prerequisite for browser enrollment", () => {
    expect(voiceCloneConfiguration({ DASHSCOPE_API_KEY: "secret" })).toMatchObject({
      configured: false,
      missing: ["S3_ENDPOINT_URL", "S3_BUCKET", "S3_AK", "S3_SK", "S3_PUBLIC_BASE_URL"],
    });
  });

  it("maps provider voices to local display names", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      output: { voice_list: [{ voice_id: "cosyvoice-v3-flash-openrt-123", status: "OK", gmt_create: "2026-08-27" }] },
    }), { status: 200 })) as unknown as typeof fetch;
    const voices = await listBailianClonedVoices(
      { "cosyvoice-v3-flash-openrt-123": "我的声音" },
      { DASHSCOPE_API_KEY: "secret", BAILIAN_API_HOST: "llm-demo.example.com" },
      fetchImpl,
    );

    expect(voices).toEqual([{
      id: "cosyvoice-v3-flash-openrt-123",
      displayName: "我的声音",
      status: "OK",
      createdAt: "2026-08-27",
    }]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://llm-demo.example.com/api/v1/services/audio/tts/customization",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });

  it("does not duplicate the active environment voice when the provider returns the same named voice", () => {
    const active = {
      id: "__active_bailian_clone__",
      displayName: "Shuchang 克隆音色",
      status: "OK" as const,
      createdAt: null,
    };
    const providerVoice = {
      id: "cosyvoice-v3-flash-shuchang-123",
      displayName: "shuchang 克隆音色",
      status: "OK" as const,
      createdAt: "2026-08-22 14:05:47",
    };

    expect(mergeBailianClonedVoiceCatalog(active, [providerVoice])).toEqual([providerVoice]);
    expect(mergeBailianClonedVoiceCatalog(
      { ...active, id: providerVoice.id },
      [{ ...providerVoice, displayName: "重新命名后的音色" }],
    )).toEqual([{ ...providerVoice, displayName: "重新命名后的音色" }]);
  });

  it("deletes a provider voice through the Bailian enrollment endpoint", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ output: {} }), { status: 200 })) as unknown as typeof fetch;

    await deleteBailianClonedVoice(
      "cosyvoice-v3-flash-openrt-123",
      { DASHSCOPE_API_KEY: "secret", BAILIAN_API_HOST: "llm-demo.example.com" },
      fetchImpl,
    );

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://llm-demo.example.com/api/v1/services/audio/tts/customization",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          model: "voice-enrollment",
          input: { action: "delete_voice", voice_id: "cosyvoice-v3-flash-openrt-123" },
        }),
      }),
    );
  });
});
