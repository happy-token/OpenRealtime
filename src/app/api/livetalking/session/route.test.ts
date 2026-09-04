import { afterEach, describe, expect, it, vi } from "vitest";

const processControl = vi.hoisted(() => ({
  ensure: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@/lib/livetalking-process", () => ({
  ensureLiveTalkingProcess: processControl.ensure,
  stopLiveTalkingProcess: processControl.stop,
}));

import { DELETE, POST } from "../../avatar-renderer/session/route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalPreview() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_EVALUATION_PREVIEW_ENABLED", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function sameOriginRequest(method: "POST" | "DELETE", body?: object) {
  return new Request("http://127.0.0.1:3010/api/avatar-renderer/session", {
    method,
    headers: {
      referer: "http://127.0.0.1:3010/",
      "sec-fetch-site": "same-origin",
      ...(body ? { "content-type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

describe("avatar renderer compatibility session route", () => {
  it("returns the external renderer binding for the default realtime idle action", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "external");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_URL", "http://renderer.internal:8010");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_PUBLIC_URL", "https://avatar.example.com");

    const response = await POST(sameOriginRequest("POST"));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      endpoint: "https://avatar.example.com",
      avatar_id: "wav2lip256-shuchang-d3d35e0f",
      avatar_name: "Shuchang",
      model: "wav2lip256",
      renderer: "livetalking-wav2lip256",
    });
    expect(processControl.ensure).not.toHaveBeenCalled();
  });

  it("does not stop the shared renderer when one browser session closes", async () => {
    enableLocalPreview();

    const response = await DELETE(sameOriginRequest("DELETE"));

    expect(response.status).toBe(204);
    expect(processControl.stop).not.toHaveBeenCalled();
  });

  it("starts the isolated Wav2Lip 96 renderer for a compatibility session", async () => {
    enableLocalPreview();

    const response = await POST(sameOriginRequest("POST", {
      renderPath: "segmented",
      segmentedAvatarId: "shuchang",
      segmentedDisplayName: "Shuchang",
      segmentedAvatarActionId: "builtin:liveportrait-optimized",
      segmentedLipSyncId: "wav2lip96",
    }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      endpoint: "http://127.0.0.1:8011",
      avatar_id: "shuchang",
      model: "wav2lip96",
      renderer: "livetalking-wav2lip96",
    });
    expect(processControl.ensure).toHaveBeenCalledWith(expect.any(String), 8011, 96);
  });

  it("reports disabled self-hosted rendering explicitly", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "disabled");

    const response = await POST(sameOriginRequest("POST"));

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: "Self-hosted avatar renderer is disabled",
    });
  });
});
