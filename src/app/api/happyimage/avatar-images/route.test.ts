import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const provider = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock("@/lib/happyimage-avatar", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/happyimage-avatar")>(),
  createHappyImageAvatar: provider.create,
}));

import { POST } from "./route";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function localMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function request(origin = "http://127.0.0.1:3010") {
  return new NextRequest("http://127.0.0.1:3010/api/happyimage/avatar-images", {
    method: "POST",
    headers: {
      "content-type": "application/json", host: "127.0.0.1:3010", origin,
      referer: "http://127.0.0.1:3010/", "sec-fetch-site": "same-origin",
    },
    body: JSON.stringify({ prompt: "portrait" }),
  });
}

describe("HappyImage Avatar route", () => {
  it("returns an owned generated image without exposing credentials", async () => {
    localMode();
    provider.create.mockResolvedValue({ imageUrl: "data:image/png;base64,AA==", taskId: "task-1" });
    const response = await POST(request());

    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ imageUrl: "data:image/png;base64,AA==" });
    expect(provider.create).toHaveBeenCalledWith(expect.any(Object), { prompt: "portrait" });
  });

  it("rejects unauthenticated and cross-origin paid generation before calling HappyImage", async () => {
    expect((await POST(request())).status).toBe(403);
    localMode();
    expect((await POST(request("https://other.example"))).status).toBe(403);
    expect(provider.create).not.toHaveBeenCalled();
  });
});
