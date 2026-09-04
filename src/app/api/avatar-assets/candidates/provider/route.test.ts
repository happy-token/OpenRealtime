import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  persist: vi.fn(),
  trustedVidu: vi.fn(),
  getVidu: vi.fn(),
  safeUrl: vi.fn(),
  trustedLtx: vi.fn(),
  getLtx: vi.fn(),
  downloadLtx: vi.fn(),
}));

vi.mock("@/lib/avatar-assets-server", async () => {
  const actual = await vi.importActual<typeof import("@/lib/avatar-assets-server")>("@/lib/avatar-assets-server");
  return {
    ...actual,
    authorizeAvatarAssetRequest: () => true,
    persistAvatarCandidate: mocks.persist,
  };
});
vi.mock("@/lib/vidu-task-coordinator", () => ({
  getTrustedLocalViduTask: mocks.trustedVidu,
}));
vi.mock("@/lib/vidu-video", () => ({
  getViduGeneration: mocks.getVidu,
  ViduProviderError: class ViduProviderError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
}));
vi.mock("@/lib/vidu-result-url", () => ({ assertSafeViduResultUrl: mocks.safeUrl }));
vi.mock("@/lib/ltx-task-coordinator", () => ({ getTrustedLocalLtxTask: mocks.trustedLtx }));
vi.mock("@/lib/video-generation-provider", () => ({
  getVideoGeneration: mocks.getLtx,
  isVideoGenerationProviderError: () => false,
}));
vi.mock("@/lib/ltx-result-video", () => ({ downloadLtxResultVideo: mocks.downloadLtx }));
vi.mock("@/lib/media-signatures", () => ({ hasMatchingVideoSignature: () => true }));
vi.mock("@/lib/liveportrait-worker", () => ({
  getLivePortraitTask: () => undefined,
  retainLivePortraitTaskArtifact: () => undefined,
}));

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function request(avatarId: string, sourceKind: "vidu" | "ltx" | "minimax" = "vidu") {
  return new Request("http://127.0.0.1:3010/api/avatar-assets/candidates/provider", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sourceKind,
      taskId: "task_123456",
      avatarId,
      idempotencyKey: "candidate-1",
      rightsConfirmed: true,
    }),
  });
}

function successfulViduResult() {
  mocks.trustedVidu.mockReturnValue({
    task: { taskId: "task_123456" },
    visualIdentityId: "shuchang",
    sourceSha256: "a".repeat(64),
  });
  mocks.getVidu.mockResolvedValue({
    state: "success",
    creations: [{ url: "https://media.vidu.test/result.mp4" }],
  });
  mocks.safeUrl.mockResolvedValue("https://media.vidu.test/result.mp4");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    Uint8Array.from([0, 0, 0, 12, 102, 116, 121, 112]),
    { headers: { "Content-Type": "video/mp4" } },
  )));
}

describe("provider Motion Base ingest", () => {
  it("derives identity from the trusted task and rejects a client mismatch", async () => {
    successfulViduResult();
    const response = await POST(request("other-person"));
    expect(response.status).toBe(409);
    expect(mocks.persist).not.toHaveBeenCalled();
  });

  it("persists using trusted task provenance", async () => {
    successfulViduResult();
    mocks.persist.mockResolvedValue(Response.json({ candidate_id: "candidate-1" }, { status: 201 }));
    const response = await POST(request("shuchang"));
    expect(response.status).toBe(201);
    expect(mocks.persist).toHaveBeenCalledWith(expect.objectContaining({ avatarId: "shuchang" }));
  });

  it("persists a MiniMax result through the compatible LTX candidate source using its trusted Avatar binding", async () => {
    mocks.trustedLtx.mockReturnValue({ visualIdentityId: "shuchang", model: "MiniMax-H3", task: { taskId: "task_123456" } });
    mocks.getLtx.mockResolvedValue({ state: "success", videoUrl: "https://media.ltx.test/result.mp4" });
    mocks.downloadLtx.mockResolvedValue({
      bytes: Uint8Array.from([0, 0, 0, 12, 102, 116, 121, 112]),
      mediaType: "video/mp4",
    });
    mocks.persist.mockResolvedValue(Response.json({ candidate_id: "candidate-ltx" }, { status: 201 }));
    const response = await POST(request("shuchang", "minimax"));
    expect(response.status).toBe(201);
    expect(mocks.persist).toHaveBeenCalledWith(expect.objectContaining({
      avatarId: "shuchang",
      sourceKind: "ltx",
    }));
    expect(mocks.getLtx).toHaveBeenCalledWith(expect.anything(), "task_123456", "MiniMax-H3");
  });

  it("does not expose unknown internal errors", async () => {
    mocks.trustedVidu.mockReturnValue(undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await POST(request("shuchang"));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ error: "Provider 候选保存失败" });
  });
});
