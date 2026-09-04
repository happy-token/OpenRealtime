import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const session = vi.hoisted(() => ({ create: vi.fn() }));

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

  it("rejects cross-origin and malformed selected avatar IDs", async () => {
    enableLocalTestMode();
    expect((await POST(localPost("{}", "http://evil.example.com"))).status).toBe(403);
    expect((await POST(localPost(JSON.stringify({ avatarId: "<script>" })))).status).toBe(400);
    expect(session.create).not.toHaveBeenCalled();
  });
});
