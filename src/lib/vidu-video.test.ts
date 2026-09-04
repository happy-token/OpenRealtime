import { describe, expect, it, vi } from "vitest";
import {
  createViduImageToVideo,
  getViduCredits,
  getViduGeneration,
  ViduProviderError,
  viduConfig,
} from "./vidu-video";

const environment = { VIDU_API_KEY: "vidu-secret", VIDU_API_URL: "https://vidu.test" };
const imageDataUrl = `data:image/png;base64,${Buffer.from("image").toString("base64")}`;

describe("Vidu video provider", () => {
  it("requires a server-side API key", () => {
    expect(() => viduConfig({})).toThrowError("Vidu 尚未配置 API Key");
  });

  it("uses the configured regional API endpoint", () => {
    expect(viduConfig({
      VIDU_API_KEY: "vidu-secret",
      VIDU_API_URL: "https://api.vidu.cn/",
    }).apiUrl).toBe("https://api.vidu.cn");
  });

  it("reads account credits without exposing the key", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ credits: 88 }), { status: 200 }));
    await expect(getViduCredits(environment, fetcher as typeof fetch)).resolves.toBe(88);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://vidu.test/ent/v2/credits?show_detail=false");
    expect(init.headers).toMatchObject({ Authorization: "Token vidu-secret" });
  });

  it("reads the current regional balance response", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      packages: [],
      remains: [
        { credit_remain: 12.5 },
        { credit_remain: 7.5 },
      ],
      general_remains: [{ credit_remain: 99 }],
      exclusive_remains: [{ credit_remain: 88 }],
    }), { status: 200 }));

    await expect(getViduCredits(environment, fetcher as typeof fetch)).resolves.toBe(20);
  });

  it("treats an authenticated account with empty balance arrays as zero credits", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      packages: [],
      remains: [],
      general_remains: [],
      exclusive_remains: [],
    }), { status: 200 }));

    await expect(getViduCredits(environment, fetcher as typeof fetch)).resolves.toBe(0);
  });

  it("supports the documented remaining_credits response", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      remaining_credits: [{ credit_remain: 16 }, { credit_remain: 4 }],
    }), { status: 200 }));
    await expect(getViduCredits(environment, fetcher as typeof fetch)).resolves.toBe(20);
  });

  it("falls back to general and exclusive balances when remains is absent", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      general_remains: [{ credit_remain: 9 }],
      exclusive_remains: [{ credit_remain: 3 }],
    }), { status: 200 }));
    await expect(getViduCredits(environment, fetcher as typeof fetch)).resolves.toBe(12);
  });

  it("creates a silent five-second Q3 Pro Fast image-to-video task", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      task_id: "task_123456",
      state: "created",
      model: "viduq3-pro-fast",
      credits: 25,
    }), { status: 200 }));

    await expect(createViduImageToVideo(environment, {
      imageDataUrl,
      prompt: "Natural breathing and occasional blinking.",
      offPeak: true,
    }, fetcher as typeof fetch)).resolves.toEqual({
      taskId: "task_123456",
      state: "created",
      model: "viduq3-pro-fast",
      credits: 25,
      offPeak: true,
    });

    const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      model: "viduq3-pro-fast",
      images: [imageDataUrl],
      prompt: "Natural breathing and occasional blinking.",
      audio: false,
      duration: 5,
      resolution: "720p",
      off_peak: true,
    });
  });

  it("maps rejected credentials to a safe provider error", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      reason: "Unauthorized",
      message: "sensitive upstream detail",
    }), { status: 401 }));
    await expect(getViduCredits(environment, fetcher as typeof fetch)).rejects.toEqual(
      new ViduProviderError("Vidu API Key 无效或无权调用当前模型", 401),
    );
  });

  it("returns only safe HTTPS creation URLs", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      state: "success",
      creations: [
        { id: "creation-1", url: "https://cdn.vidu.test/video.mp4", cover_url: "https://cdn.vidu.test/cover.jpg" },
        { id: "creation-2", url: "javascript:alert(1)" },
      ],
    }), { status: 200 }));
    await expect(getViduGeneration(environment, "task_123456", fetcher as typeof fetch))
      .resolves.toEqual({
        taskId: "task_123456",
        state: "success",
        errorCode: undefined,
        creations: [{
          id: "creation-1",
          url: "https://cdn.vidu.test/video.mp4",
          coverUrl: "https://cdn.vidu.test/cover.jpg",
        }],
      });
  });
});
