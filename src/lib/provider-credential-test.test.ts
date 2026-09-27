import { describe, expect, it, vi } from "vitest";
import { testProviderCredential, testStreamingLlmInstance } from "./provider-credential-test";

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

describe("streaming LLM instance checks", () => {
  it("requires two incremental text events and reports host first-text latency", async () => {
    const response = new Response('data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
      + 'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
      + 'data: [DONE]\n\n', { headers: { "Content-Type": "text/event-stream" } });
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toContain("api.openai.com");
      expect(init?.method).toBe("POST");
      return response;
    });
    const result = await testStreamingLlmInstance("openai", "private-key", "gpt-test", fetcher as typeof fetch);
    expect(result.ok).toBe(true);
    expect(result.firstTextMs).toBeGreaterThanOrEqual(0);
    expect(fetcher).toHaveBeenCalledWith("https://api.openai.com/v1/chat/completions", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ Authorization: "Bearer private-key" }),
    }));
    expect(JSON.parse(fetcher.mock.calls[0]?.[1]?.body as string).model).toBe("gpt-test");
    expect(JSON.stringify(result)).not.toContain("private-key");
    expect(JSON.stringify(result)).not.toContain("你好");
  });

  it("does not call a one-chunk or empty response realtime streaming", async () => {
    const one = new Response('data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n');
    const result = await testStreamingLlmInstance("deepseek", "private-key", "", vi.fn(async () => one) as typeof fetch);
    expect(result.ok).toBe(false);
    expect(result.firstTextMs).toBeUndefined();
  });
});
