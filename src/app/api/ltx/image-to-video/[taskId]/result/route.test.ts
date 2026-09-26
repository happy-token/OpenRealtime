import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { providerKeyFingerprint } from "@/lib/provider-api-key";

const mocks = vi.hoisted(() => ({
  trusted: vi.fn(),
  status: vi.fn(),
  download: vi.fn(),
}));

vi.mock("@/lib/ltx-task-coordinator", () => ({ getTrustedLocalLtxTask: mocks.trusted }));
vi.mock("@/lib/video-generation-provider", () => ({
  getVideoGeneration: mocks.status,
  isVideoGenerationProviderError: () => false,
}));
vi.mock("@/lib/ltx-result-video", () => ({ downloadLtxResultVideo: mocks.download }));

import { GET } from "./route";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function request() {
  return new NextRequest("http://127.0.0.1:3010/api/ltx/image-to-video/task_123456/result", {
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

describe("LTX result proxy", () => {
  it("serves only a completed trusted task through same-origin bytes", async () => {
    enableLocalTestMode();
    vi.stubEnv("MINIMAX_API_KEY", "test-minimax-key");
    mocks.trusted.mockReturnValue({ visualIdentityId: "avatar-123", model: "MiniMax-H3", credentialFingerprint: providerKeyFingerprint("test-minimax-key") });
    mocks.status.mockResolvedValue({ state: "success", videoUrl: "https://media.ltx.test/result.mp4" });
    mocks.download.mockResolvedValue({ bytes: Uint8Array.from([0, 0, 0, 12]), mediaType: "video/mp4" });
    const response = await GET(request(), { params: Promise.resolve({ taskId: "task_123456" }) });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("video/mp4");
    expect(mocks.download).toHaveBeenCalledWith("https://media.ltx.test/result.mp4");
    expect(mocks.status).toHaveBeenCalledWith(expect.anything(), "task_123456", "MiniMax-H3");
  });
});
