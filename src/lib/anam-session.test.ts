import { describe, expect, it, vi } from "vitest";
import {
  anamSessionConfig,
  AnamSessionError,
  createAnamSessionToken,
} from "./anam-session";

const environment = {
  ANAM_API_KEY: "anam-key",
  ANAM_AVATAR_ID: "avatar-shuchang",
  ANAM_AVATAR_MODEL: "cara-4",
};

describe("anamSessionConfig", () => {
  it("requires the API key and selected avatar", () => {
    expect(() => anamSessionConfig({})).toThrowError("Anam 尚未配置 API Key");
    expect(() => anamSessionConfig({ ANAM_API_KEY: "key" }))
      .toThrowError("尚未选择 Anam 人物形象");
  });

  it("defaults to the current Cara model", () => {
    expect(anamSessionConfig({
      ANAM_API_KEY: "key",
      ANAM_AVATAR_ID: "avatar",
    }).avatarModel).toBe("cara-4");
  });
});

describe("createAnamSessionToken", () => {
  it("requests an audio passthrough session without exposing the key", async () => {
    const fetcher = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response(
      JSON.stringify({ sessionToken: "short-lived-token" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));

    await expect(createAnamSessionToken(environment, fetcher as typeof fetch))
      .resolves.toEqual({
        sessionToken: "short-lived-token",
        avatarId: "avatar-shuchang",
        avatarModel: "cara-4",
      });

    const request = fetcher.mock.calls[0];
    expect(request?.[0]).toBe("https://api.anam.ai/v1/auth/session-token");
    const options = request?.[1];
    expect(options).toBeDefined();
    if (!options) throw new Error("Expected Anam request options");
    expect(options.headers).toEqual({
      Authorization: "Bearer anam-key",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(options.body))).toEqual({
      personaConfig: {
        avatarId: "avatar-shuchang",
        avatarModel: "cara-4",
        enableAudioPassthrough: true,
      },
    });
  });

  it("maps rejected credentials to a safe error", async () => {
    const fetcher = vi.fn(async () => new Response(
      JSON.stringify({ message: "unauthorized" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ));
    await expect(createAnamSessionToken(environment, fetcher as typeof fetch))
      .rejects.toEqual(new AnamSessionError("Anam API Key 无效或无权使用该 Avatar", 401));
  });
});
