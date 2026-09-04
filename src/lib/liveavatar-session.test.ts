import { describe, expect, it, vi } from "vitest";
import {
  createLiveAvatarSessionToken,
  LiveAvatarSessionError,
  liveAvatarSessionConfig,
} from "./liveavatar-session";

const environment = {
  LIVEAVATAR_API_KEY: "secret-key",
  LIVEAVATAR_AVATAR_ID: "avatar-123",
  LIVEAVATAR_SANDBOX: "true",
};

describe("LiveAvatar session token client", () => {
  it("requires both server-side credentials", () => {
    expect(() => liveAvatarSessionConfig({}))
      .toThrowError(LiveAvatarSessionError);
  });

  it("never substitutes a public avatar when the configured avatar is missing", () => {
    expect(() => liveAvatarSessionConfig({ LIVEAVATAR_API_KEY: "key" }))
      .toThrowError("尚未选择 HeyGen 人物形象，请先配置 Avatar ID");
    expect(() => liveAvatarSessionConfig({
      LIVEAVATAR_API_KEY: "key",
      LIVEAVATAR_SANDBOX: "true",
    })).toThrowError(LiveAvatarSessionError);
  });

  it("creates a LITE sandbox session without exposing the API key", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      data: { session_token: "short-lived-token", session_id: "session-1" },
    }), { status: 200 }));

    const result = await createLiveAvatarSessionToken(environment, fetcher as typeof fetch);

    expect(result).toEqual({ sessionToken: "short-lived-token", sessionId: "session-1" });
    expect(fetcher).toHaveBeenCalledOnce();
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.liveavatar.com/v1/sessions/token");
    expect(init.headers).toMatchObject({ "X-API-KEY": "secret-key" });
    expect(JSON.parse(String(init.body))).toEqual({
      mode: "LITE",
      avatar_id: "avatar-123",
      is_sandbox: true,
    });
    expect(JSON.stringify(result)).not.toContain("secret-key");
  });

  it("returns a safe authorization error without provider response details", async () => {
    const fetcher = vi.fn(async () => new Response("sensitive provider body", { status: 403 }));

    await expect(createLiveAvatarSessionToken(environment, fetcher as typeof fetch))
      .rejects.toMatchObject({
        status: 403,
        message: "LiveAvatar API Key 无效或无权使用该 Avatar",
      });
  });
});
