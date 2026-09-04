import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "@/lib/avatar-test-access";
import { createLivePortraitMotionConfig } from "@/lib/liveportrait-motion-config";

const worker = vi.hoisted(() => ({
  inspect: vi.fn(),
  create: vi.fn(),
  DrivingValidationError: class DrivingValidationError extends Error {},
  TaskConflictError: class TaskConflictError extends Error {},
}));

vi.mock("@/lib/liveportrait-worker", () => ({
  inspectLivePortraitWorker: worker.inspect,
  createOrReuseLivePortraitTask: worker.create,
  LivePortraitDrivingValidationError: worker.DrivingValidationError,
  LivePortraitTaskConflictError: worker.TaskConflictError,
}));

import { GET, POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function headers(extra: Record<string, string> = {}) {
  return {
    host: "127.0.0.1:3010",
    origin: "http://127.0.0.1:3010",
    "sec-fetch-site": "same-origin",
    ...extra,
  };
}

describe("LivePortrait worker route", () => {
  it("rejects untrusted status and mutation requests", async () => {
    expect((await GET(new NextRequest("http://127.0.0.1:3010/api/liveportrait"))).status).toBe(403);
    expect((await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait", {
      method: "POST",
      headers: { "x-openrealtime-client": "digital-human-video-ui" },
    }))).status).toBe(403);
  });

  it("reports pinned local runtime readiness", async () => {
    enableLocalTestMode();
    worker.inspect.mockResolvedValue({
      ready: true,
      device: "mps",
      weightsBytes: 658_941_445,
      issues: [],
      templates: [{ id: "breathing", available: true }],
    });
    const response = await GET(new NextRequest("http://127.0.0.1:3010/api/liveportrait", { headers: headers() }));
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ ready: true, device: "mps", local_only: true });
  });

  it("requires same-origin rights-confirmed input and creates one task", async () => {
    enableLocalTestMode();
    const form = new FormData();
    form.set("source", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
    form.set("avatarId", "shuchang");
    form.set("driverId", "sweet-vitality");
    const livePortraitConfig = createLivePortraitMotionConfig();
    form.set("livePortraitConfig", JSON.stringify(livePortraitConfig));
    form.set("rightsConfirmed", "true");
    worker.create.mockResolvedValue({
      task: { id: "11111111-1111-4111-8111-111111111111", state: "processing", driverId: "breathing", createdAt: "2026-08-24T00:00:00Z" },
      reused: false,
    });
    const request = new NextRequest("http://127.0.0.1:3010/api/liveportrait", {
      method: "POST",
      headers: headers({ "content-length": "1024" }),
      body: form,
    });
    expect(canUseAvatarTestApis(request)).toBe(true);
    expect(isSameOriginAvatarMutation(request)).toBe(true);
    const response = await POST(request);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ task_id: "11111111-1111-4111-8111-111111111111", state: "processing" });
    expect(worker.create).toHaveBeenCalledOnce();
    expect(worker.create).toHaveBeenCalledWith(expect.objectContaining({
      visualIdentityId: "shuchang",
      livePortraitConfig,
    }));
  });

  it("rejects missing rights confirmation before starting the worker", async () => {
    enableLocalTestMode();
    const form = new FormData();
    form.set("source", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
    form.set("avatarId", "shuchang");
    form.set("driverId", "breathing");
    const request = new NextRequest("http://127.0.0.1:3010/api/liveportrait", {
      method: "POST",
      headers: headers({ "content-length": "1024" }),
      body: form,
    });
    expect(canUseAvatarTestApis(request)).toBe(true);
    expect(isSameOriginAvatarMutation(request)).toBe(true);
    const response = await POST(request);
    expect(response.status).toBe(400);
    expect(worker.create).not.toHaveBeenCalled();
  });

  it("allows an emotional companion built-in to create an action task", async () => {
    enableLocalTestMode();
    const form = new FormData();
    form.set("source", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
    form.set("avatarId", "shuchang");
    form.set("driverId", "melancholy-empathy");
    form.set("livePortraitConfig", JSON.stringify(createLivePortraitMotionConfig()));
    form.set("rightsConfirmed", "true");
    worker.create.mockResolvedValue({
      task: { id: "22222222-2222-4222-8222-222222222222", state: "processing", driverId: "melancholy-empathy", createdAt: "2026-08-31T00:00:00Z" },
      reused: false,
    });
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait", {
      method: "POST",
      headers: headers({ "content-length": "1024" }),
      body: form,
    }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      task_id: "22222222-2222-4222-8222-222222222222",
      state: "processing",
    });
    expect(worker.create).toHaveBeenCalledWith(expect.objectContaining({ driverId: "melancholy-empathy" }));
  });

  it("returns the closed-mouth validation reason before queuing an uploaded driving video", async () => {
    enableLocalTestMode();
    const form = new FormData();
    form.set("source", new File([Uint8Array.from([255, 216, 255, 0])], "portrait.jpg", { type: "image/jpeg" }));
    form.set("avatarId", "shuchang");
    form.set("driverId", "upload");
    form.set("driving", new File([
      Uint8Array.from([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109]),
    ], "talking.mp4", { type: "video/mp4" }));
    form.set("livePortraitConfig", JSON.stringify(createLivePortraitMotionConfig()));
    form.set("rightsConfirmed", "true");
    worker.create.mockRejectedValue(new worker.DrivingValidationError(
      "参考视频包含明显说话口型或大幅嘴部运动，请重新录制闭嘴表演",
    ));
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/liveportrait", {
      method: "POST",
      headers: headers({ "content-length": "2048" }),
      body: form,
    }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "参考视频包含明显说话口型或大幅嘴部运动，请重新录制闭嘴表演",
    });
  });
});
