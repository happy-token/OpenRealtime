import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { providerKeyCookieName, sealProviderKey } from "@/lib/provider-api-key";

const session = vi.hoisted(() => ({ create: vi.fn() }));
const account = vi.hoisted(() => ({ user: vi.fn(), key: vi.fn(), owns: vi.fn() }));

vi.mock("@/lib/user-session", () => ({ USER_SESSION_COOKIE: "openrealtime_user_session", userFromRequest: account.user }));
vi.mock("@/lib/user-provider-credentials", () => ({ loadPersonalKeyVersion: account.key }));
vi.mock("@/lib/voice-admission", () => ({ claimAnamVoiceTicket: account.owns }));

vi.mock("@/lib/anam-session", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/anam-session")>();
  return { ...original, createAnamSessionToken: session.create };
});

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
  vi.stubEnv("ANAM_API_KEY", "anam-key");
  vi.stubEnv("ANAM_AVATAR_ID", "fallback-avatar");
  vi.stubEnv("ANAM_AVATAR_MODEL", "cara-4");
}

function localPost(body?: string, origin = "http://127.0.0.1:3010") {
  return new NextRequest("http://127.0.0.1:3010/api/anam/session", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3010",
      origin,
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
    },
    body,
  });
}

describe("Anam session route", () => {
  it("rejects the legacy forgeable header", async () => {
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/anam/session", {
      method: "POST",
      headers: { "x-openrealtime-client": "voice-ui" },
    }));
    expect(response.status).toBe(403);
  });

  it("uses the independently selected hosted avatar", async () => {
    enableLocalTestMode();
    session.create.mockResolvedValue({ sessionToken: "token", avatarId: "selected-avatar", avatarModel: "cara-4" });
    const response = await POST(localPost(JSON.stringify({ avatarId: "selected-avatar" })));
    expect(response.status).toBe(200);
    expect(session.create).toHaveBeenCalledWith(expect.objectContaining({ ANAM_AVATAR_ID: "selected-avatar" }));
  });

  it("uses a browser-session key when the server Anam key is absent", async () => {
    enableLocalTestMode();
    vi.stubEnv("ANAM_API_KEY", "");
    vi.stubEnv("VOICEAGENT_ADMIN_SESSION_SECRET", "s".repeat(32));
    session.create.mockResolvedValue({ sessionToken: "token", avatarId: "selected-avatar", avatarModel: "cara-4" });
    const request = localPost(JSON.stringify({ avatarId: "selected-avatar" }));
    request.headers.set("cookie", `${providerKeyCookieName("anam")}=${sealProviderKey("user-anam-api-key")}`);
    expect((await POST(request)).status).toBe(200);
    expect(session.create).toHaveBeenCalledWith(expect.objectContaining({ ANAM_API_KEY: "user-anam-api-key" }));
  });

  it("rejects cross-origin and malformed selected avatar IDs", async () => {
    enableLocalTestMode();
    expect((await POST(localPost("{}", "http://evil.example.com"))).status).toBe(403);
    expect((await POST(localPost(JSON.stringify({ avatarId: "<script>" })))).status).toBe(400);
    expect(session.create).not.toHaveBeenCalled();
  });

  it("limits public Anam access to a ticket owner and the published avatar", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("VOICEAGENT_PUBLIC_VOICE_ENABLED", "true");
    vi.stubEnv("VOICEAGENT_ENDPOINT_AUTH_MODE", "public_ticket");
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    vi.stubEnv("ANAM_AVATAR_ID", "published-avatar");
    account.user.mockResolvedValue({ issuer: "https://identity.test", subject: "owner" });
    account.owns.mockResolvedValue(false);
    const ticket = "x".repeat(43);
    expect((await POST(localPost(JSON.stringify({ admission: ticket })))).status).toBe(403);
    account.owns.mockResolvedValue({ source: "platform", version: null });
    expect((await POST(localPost(JSON.stringify({ admission: ticket, avatarId: "someone-else" })))).status).toBe(403);
    account.owns.mockResolvedValue({ source: "personal", version: "38ff0333-901c-493a-9766-54a7284cfbd1" });
    account.key.mockResolvedValue("owner-anam-key");
    session.create.mockResolvedValue({ sessionToken: "token", avatarId: "published-avatar", avatarModel: "cara-4" });
    expect((await POST(localPost(JSON.stringify({ admission: ticket })))).status).toBe(200);
    expect(account.key).toHaveBeenCalledWith({ issuer: "https://identity.test", subject: "owner" }, "anam", "38ff0333-901c-493a-9766-54a7284cfbd1");
    expect(session.create).toHaveBeenCalledWith(expect.objectContaining({ ANAM_API_KEY: "owner-anam-key" }));
    expect((await POST(localPost(JSON.stringify({ admission: ticket, avatarId: "private-avatar" })))).status).toBe(200);
    expect(session.create).toHaveBeenCalledWith(expect.objectContaining({ ANAM_AVATAR_ID: "private-avatar", ANAM_API_KEY: "owner-anam-key" }));
  });

  it("reports whose Anam quota failed without returning provider text or falling back", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("VOICEAGENT_PUBLIC_VOICE_ENABLED", "true");
    vi.stubEnv("VOICEAGENT_ENDPOINT_AUTH_MODE", "public_ticket");
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    vi.stubEnv("ANAM_AVATAR_ID", "published-avatar");
    account.user.mockResolvedValue({ issuer: "https://identity.test", subject: "owner" });
    account.owns.mockResolvedValue({ source: "personal", version: "38ff0333-901c-493a-9766-54a7284cfbd1" });
    account.key.mockResolvedValue("owner-anam-key");
    const { AnamSessionError } = await import("@/lib/anam-session");
    session.create.mockRejectedValue(new AnamSessionError("insufficient credit, secret=owner-anam-key", 402));
    const response = await POST(localPost(JSON.stringify({ admission: "x".repeat(43) })));
    expect(response.status).toBe(402);
    const body = await response.text();
    expect(body).toContain("你的 Anam 额度不足");
    expect(body).not.toContain("owner-anam-key");
    expect(session.create).toHaveBeenCalledTimes(1);
  });
});
