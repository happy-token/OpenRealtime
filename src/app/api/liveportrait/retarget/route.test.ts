import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG } from "@/lib/liveportrait-retarget-config";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function trustedHeaders() {
  return {
    host: "127.0.0.1:3010",
    origin: "http://127.0.0.1:3010",
    "sec-fetch-site": "same-origin",
    "content-length": "1024",
  };
}

function poseForm({ rightsConfirmed = true, headYaw = 0 } = {}) {
  const form = new FormData();
  form.set("source", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
  form.set("retargetConfig", JSON.stringify({
    ...LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
    head_yaw: headYaw,
  }));
  form.set("rightsConfirmed", rightsConfirmed ? "true" : "false");
  return form;
}

describe("LivePortrait single-image retarget route", () => {
  it("rejects an untrusted mutation", async () => {
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait/retarget", {
      method: "POST",
      headers: { "content-length": "1024" },
      body: poseForm(),
    }));
    expect(response.status).toBe(403);
  });

  it("requires source-image rights confirmation", async () => {
    enableLocalTestMode();
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait/retarget", {
      method: "POST",
      headers: trustedHeaders(),
      body: poseForm({ rightsConfirmed: false }),
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: expect.stringContaining("使用权") });
  });

  it("rejects out-of-range manual pose controls before running inference", async () => {
    enableLocalTestMode();
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait/retarget", {
      method: "POST",
      headers: trustedHeaders(),
      body: poseForm({ headYaw: 26 }),
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: expect.stringContaining("head_yaw") });
  });
});
