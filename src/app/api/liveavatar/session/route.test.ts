import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { POST } from "./route";
import { ADMIN_SESSION_COOKIE, createAdminSessionToken } from "@/lib/admin-auth";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("rejects self-declared clients before contacting the paid provider", async () => {
  vi.stubEnv("NODE_ENV", "production");
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const response = await POST(new NextRequest("https://voice.example/api/liveavatar/session", {
    method: "POST", headers: { "x-openrealtime-client": "voice-ui", origin: "https://voice.example" },
  }));
  expect(response.status).toBe(403);
  expect(fetcher).not.toHaveBeenCalled();
});

it("allows authenticated same-origin sessions but rejects a different origin", async () => {
  vi.stubEnv("NODE_ENV", "production");
  const config = { username: "admin", password: "long-password-123", sessionSecret: "s".repeat(32) };
  vi.stubEnv("VOICEAGENT_ADMIN_USERNAME", config.username);
  vi.stubEnv("VOICEAGENT_ADMIN_PASSWORD", config.password);
  vi.stubEnv("VOICEAGENT_ADMIN_SESSION_SECRET", config.sessionSecret);
  vi.stubEnv("LIVEAVATAR_API_KEY", "key"); vi.stubEnv("LIVEAVATAR_AVATAR_ID", "avatar");
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { session_token: "token", session_id: "session" } })));
  vi.stubGlobal("fetch", fetcher);
  const cookie = `${ADMIN_SESSION_COOKIE}=${createAdminSessionToken(config)}`;
  const denied = await POST(new NextRequest("https://voice.example/api/liveavatar/session", {
    method: "POST", headers: { cookie, origin: "https://untrusted.example" },
  }));
  expect(denied.status).toBe(403);
  expect(fetcher).not.toHaveBeenCalled();
  const response = await POST(new NextRequest("https://voice.example/api/liveavatar/session", {
    method: "POST", headers: { cookie, origin: "https://voice.example" },
  }));
  expect(response.status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
