import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "@/lib/avatar-test-access";
import { POST } from "./route";

afterEach(() => vi.unstubAllEnvs());

function localPost(headers: Record<string, string> = {}) {
  return new NextRequest("http://127.0.0.1:3010/api/vidu/image-to-video", {
    method: "POST",
    headers: {
      origin: "http://localhost:3010",
      "sec-fetch-site": "same-origin",
      ...headers,
    },
  });
}

describe("Vidu image-to-video route", () => {
  it("rejects the old forgeable client header", async () => {
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/vidu/image-to-video", {
      method: "POST",
      headers: { "x-openrealtime-client": "digital-human-video-ui" },
    }));
    expect(response.status).toBe(403);
  });

  it("requires the loopback launcher marker for local test access", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    const response = await POST(localPost());
    expect(response.status).toBe(403);
  });

  it("rejects a missing Content-Length before buffering multipart input", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    const request = localPost();
    expect(canUseAvatarTestApis(request)).toBe(true);
    expect(isSameOriginAvatarMutation(request)).toBe(true);
    const response = await POST(request);
    expect(response.status).toBe(411);
    await expect(response.json()).resolves.toMatchObject({ error: expect.stringContaining("Content-Length") });
  });

  it("rejects a cross-origin paid request", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    const response = await POST(localPost({ origin: "http://evil.example.com" }));
    expect(response.status).toBe(403);
  });

  it("requires a valid avatar_id before creating a task", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    const form = new FormData();
    form.set("image", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
    form.set("prompt", "natural idle");
    form.set("creditsAccepted", "true");
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/vidu/image-to-video", {
      method: "POST",
      headers: {
        host: "127.0.0.1:3010",
        origin: "http://127.0.0.1:3010",
        "sec-fetch-site": "same-origin",
        "content-length": "1024",
      },
      body: form,
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "avatar_id 无效" });
  });
});
