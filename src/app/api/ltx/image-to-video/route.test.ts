import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({
  readImage: vi.fn(),
  createTask: vi.fn(),
  submit: vi.fn(),
  prepareFrame: vi.fn(),
}));

vi.mock("@/lib/avatar-catalog-repository", () => ({ readOwnedAvatarImage: mocks.readImage }));
vi.mock("@/lib/avatar-test-access", () => ({
  canUseAvatarTestApis: () => true,
  isSameOriginAvatarMutation: () => true,
}));
vi.mock("@/lib/ltx-task-coordinator", () => ({
  createOrReuseLocalLtxTask: mocks.createTask,
  LtxTaskConflictError: class LtxTaskConflictError extends Error {},
}));
vi.mock("@/lib/minimax-frame-image", () => ({ prepareMiniMaxFrameImage: mocks.prepareFrame }));
vi.mock("@/lib/video-generation-provider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/video-generation-provider")>("@/lib/video-generation-provider");
  return { ...actual, createImageToVideo: mocks.submit };
});

import { GET, POST } from "./route";

beforeEach(() => {
  mocks.prepareFrame.mockImplementation(async (bytes, mediaType) => ({ bytes, mediaType, transformed: false }));
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
  vi.stubEnv("LTX_API_KEY", "test-key");
  vi.stubEnv("MINIMAX_API_KEY", "minimax-test-key");
}

function request(overrides: Record<string, unknown> = {}) {
  const body = JSON.stringify({
    avatarId: "avatar-123",
    prompt: "front-facing idle",
    model: "ltx-2-3-fast",
    creditsAccepted: true,
    rightsConfirmed: true,
    ...overrides,
  });
  return new NextRequest("http://127.0.0.1:3010/api/ltx/image-to-video", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
      "content-length": String(Buffer.byteLength(body)),
    },
    body,
  });
}

function multipartRequest() {
  const form = new FormData();
  form.set("avatarId", "avatar-123");
  form.set("prompt", "follow the reference motion");
  form.set("model", "MiniMax-H3-Context-IR");
  form.set("ratio", "9:16");
  form.set("resolution", "2K");
  form.set("duration", "8");
  form.set("imageRole", "reference_image");
  form.set("referenceVideo", new File([Uint8Array.from([0, 0, 0, 12])], "motion.mp4", { type: "video/mp4" }));
  form.set("creditsAccepted", "true");
  form.set("rightsConfirmed", "true");
  return new NextRequest("http://127.0.0.1:3010/api/ltx/image-to-video", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
      "content-length": "1024",
    },
    body: form,
  });
}

describe("LTX image-to-video route", () => {
  it("does not advertise in-memory LTX coordination as ready in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("LTX_API_KEY", "test-key");
    vi.stubEnv("MINIMAX_API_KEY", "minimax-test-key");
    const response = await GET(new NextRequest("http://127.0.0.1:3010/api/ltx/image-to-video", {
      headers: { cookie: "openrealtime_admin=test" },
    }));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({ ready: false, configured: true });
  });

  it("uses the server-owned Avatar image and returns the trusted async task", async () => {
    enableLocalTestMode();
    mocks.readImage.mockResolvedValue({ bytes: Uint8Array.from([137, 80, 78, 71]), mediaType: "image/png" });
    mocks.createTask.mockImplementation(async (_provenance, create) => ({ task: await create(), reused: false }));
    mocks.submit.mockResolvedValue({ taskId: "task_123456", state: "queueing", model: "ltx-2-3-fast", createdAt: "2026-08-31T10:00:00Z" });
    const response = await POST(request());
    expect(response.status).toBe(202);
    expect(mocks.readImage).toHaveBeenCalledWith("avatar-123");
    expect(mocks.submit).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      model: "ltx-2-3-fast",
      prompt: "front-facing idle",
      imageDataUrl: expect.stringMatching(/^data:image\/png;base64,/),
    }));
  });

  it("requires explicit paid-generation acknowledgement", async () => {
    enableLocalTestMode();
    const response = await POST(request({ creditsAccepted: false }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: expect.stringContaining("额度") });
    expect(mocks.readImage).not.toHaveBeenCalled();
  });

  it("routes MiniMax H3 through the same trusted Avatar action coordinator", async () => {
    enableLocalTestMode();
    mocks.readImage.mockResolvedValue({ bytes: Uint8Array.from([137, 80, 78, 71]), mediaType: "image/png" });
    mocks.createTask.mockImplementation(async (_provenance, create) => ({ task: await create(), reused: false }));
    mocks.submit.mockResolvedValue({ taskId: "437132157129088", state: "queueing", model: "MiniMax-H3", createdAt: "2026-09-01T15:00:00Z" });

    mocks.prepareFrame.mockResolvedValue({
      bytes: Uint8Array.from([82, 73, 70, 70]),
      mediaType: "image/webp",
      transformed: true,
    });
    const response = await POST(request({
      model: "MiniMax-H3",
      ratio: "16:9",
      duration: 6,
      imageRole: "first_and_last_frame",
    }));

    expect(response.status).toBe(202);
    expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({
      MINIMAX_API_KEY: "minimax-test-key",
    }), expect.objectContaining({
      model: "MiniMax-H3",
      ratio: "16:9",
      duration: 6,
      imageRole: "first_and_last_frame",
      imageDataUrl: expect.stringMatching(/^data:image\/webp;base64,/),
    }));
    expect(mocks.prepareFrame).toHaveBeenCalledWith(expect.any(Uint8Array), "image/png", "16:9");
  });

  it("accepts a multimodal reference video with explicit role and generation parameters", async () => {
    enableLocalTestMode();
    mocks.readImage.mockResolvedValue({ bytes: Uint8Array.from([137, 80, 78, 71]), mediaType: "image/png" });
    mocks.createTask.mockImplementation(async (_provenance, create) => ({ task: await create(), reused: false }));
    mocks.submit.mockResolvedValue({ taskId: "context_123456", state: "queueing", model: "MiniMax-H3-Context-IR", createdAt: "2026-09-02T10:00:00Z" });

    const response = await POST(multipartRequest());

    expect(response.status).toBe(202);
    expect(mocks.submit).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      model: "MiniMax-H3-Context-IR",
      ratio: "9:16",
      resolution: "2K",
      duration: 8,
      imageRole: "reference_image",
      referenceVideo: expect.objectContaining({ mediaType: "video/mp4", filename: "motion.mp4" }),
    }));
    expect(mocks.createTask).toHaveBeenCalledWith(expect.objectContaining({
      referenceVideoSha256: expect.stringMatching(/^[a-f0-9]{64}$/),
    }), expect.any(Function));
  });
});
