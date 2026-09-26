import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { providerApiKey } from "@/lib/provider-api-key";
import { GET, POST } from "./route";

afterEach(() => vi.unstubAllEnvs());

function localMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
  vi.stubEnv("VOICEAGENT_ADMIN_SESSION_SECRET", "s".repeat(32));
  vi.stubEnv("ANAM_API_KEY", "");
  vi.stubEnv("MINIMAX_API_KEY", "");
}

function request(path: string, body?: object, origin = "http://127.0.0.1:3010") {
  return new NextRequest(`http://127.0.0.1:3010/api/provider-key${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      host: "127.0.0.1:3010", origin, referer: "http://127.0.0.1:3010/", "sec-fetch-site": "same-origin",
      ...(body ? { "content-type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

describe("session-scoped provider API keys", () => {
  it("uses a sealed HttpOnly cookie without exposing the submitted key", async () => {
    localMode();
    const key = "user-owned-anam-key";
    const response = await POST(request("", { provider: "anam", apiKey: key }));
    expect(response.status).toBe(200);
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=strict");
    expect(cookie).not.toContain(key);
    const nameValue = cookie.split(";")[0];
    const followup = request("?provider=anam");
    followup.headers.set("cookie", nameValue);
    expect(providerApiKey(followup, "anam")).toBe(key);
    await expect(GET(followup).then((result) => result.json())).resolves.toEqual({ configured: true });
  });

  it("uses the server key as fallback when the user has not submitted one", async () => {
    localMode();
    vi.stubEnv("MINIMAX_API_KEY", "server-minimax-key");
    expect(providerApiKey(request("?provider=minimax"), "minimax")).toBe("server-minimax-key");
    await expect(GET(request("?provider=minimax")).then((result) => result.json())).resolves.toEqual({ configured: true });
  });

  it("does not fall back to the server key when a personal cookie is invalid", async () => {
    localMode();
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    const followup = request("?provider=anam");
    followup.headers.set("cookie", "openrealtime_anam_key=invalid");
    expect(providerApiKey(followup, "anam")).toBeUndefined();
    await expect(GET(followup).then((result) => result.json())).resolves.toEqual({ configured: false });
  });

  it("rejects cross-origin writes and invalid input", async () => {
    localMode();
    expect((await POST(request("", { provider: "anam", apiKey: "user-owned-key" }, "https://other.test"))).status).toBe(403);
    expect((await POST(request("", { provider: "anam", apiKey: " bad " }))).status).toBe(400);
  });
});
