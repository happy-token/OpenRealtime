import { describe, expect, it, vi } from "vitest";
import { testProviderCredential } from "./provider-credential-test";

describe("supplier connection checks", () => {
  it("checks an LLM credential against the provider's model list", async () => {
    const fetcher = vi.fn(async () => Response.json({ data: [{ id: "model" }] }));
    const result = await testProviderCredential("deepseek", "private-key", fetcher as typeof fetch);

    expect(result.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledWith("https://api.deepseek.com/models", expect.objectContaining({
      headers: { Authorization: "Bearer private-key" },
    }));
    expect(JSON.stringify(result)).not.toContain("private-key");
  });

  it("accepts the Model Studio response shape for a shared voice and Qwen key", async () => {
    const fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("dashscope.aliyuncs.com/api/v1/models/permissions");
      return Response.json({ output: { permissions: [] } });
    });
    const result = await testProviderCredential("dashscope", "private-key", fetcher as typeof fetch);
    expect(result.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("requires actual audio from a short Doubao speech test", async () => {
    const fetcher = vi.fn(async () => new Response('data: {"code":0,"data":"YQ=="}\n'));
    const result = await testProviderCredential("doubao", "private-key", fetcher as typeof fetch);

    expect(result.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledWith(
      "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
      expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "X-Api-Key": "private-key" }) }),
    );
    expect(JSON.stringify(result)).not.toContain("private-key");
    expect((await testProviderCredential("doubao", "private-key", vi.fn(async () => new Response('data: {"code":401,"message":"bad key"}\n')) as typeof fetch)).ok).toBe(false);
    expect((await testProviderCredential("doubao", "private-key", vi.fn(async () => new Response('data: {"code":0,"data":"YQ=="}\ndata: {"code":401}\n')) as typeof fetch)).ok).toBe(false);
  });

  it("reports a vendor rejection without returning its response body", async () => {
    const result = await testProviderCredential("openai", "private-key", vi.fn(async () => new Response("private-key", { status: 401 })) as typeof fetch);
    expect(result).toEqual({ ok: false, message: "测试未通过（服务返回 401）" });
  });
});
