import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({
  trusted: vi.fn(),
  release: vi.fn(),
  status: vi.fn(),
}));

vi.mock("@/lib/ltx-task-coordinator", () => ({
  getTrustedLocalLtxTask: mocks.trusted,
  releaseLocalLtxTask: mocks.release,
}));
vi.mock("@/lib/video-generation-provider", () => ({
  getVideoGeneration: mocks.status,
  isVideoGenerationProviderError: () => false,
}));

import { GET } from "./route";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function request(taskId = "task_123456") {
  return new NextRequest(`http://127.0.0.1:3010/api/ltx/image-to-video/${taskId}`, {
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

describe("LTX task status route", () => {
  it("does not query arbitrary LTX tasks without trusted local provenance", async () => {
    enableLocalTestMode();
    const response = await GET(request(), { params: Promise.resolve({ taskId: "task_123456" }) });
    expect(response.status).toBe(404);
    expect(mocks.status).not.toHaveBeenCalled();
  });

  it("returns a same-origin result URL and releases the active slot on success", async () => {
    enableLocalTestMode();
    mocks.trusted.mockReturnValue({ model: "ltx-2-3-fast" });
    mocks.status.mockResolvedValue({
      taskId: "task_123456",
      state: "success",
      videoUrl: "https://remote.ltx.test/result.mp4",
    });
    const response = await GET(request(), { params: Promise.resolve({ taskId: "task_123456" }) });
    await expect(response.json()).resolves.toMatchObject({
      task_id: "task_123456",
      state: "success",
      result_url: "/api/ltx/image-to-video/task_123456/result",
    });
    expect(mocks.release).toHaveBeenCalledWith("task_123456");
    expect(mocks.status).toHaveBeenCalledWith(expect.anything(), "task_123456", "ltx-2-3-fast");
  });
});
