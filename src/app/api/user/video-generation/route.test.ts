import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({
  userFromRequest: vi.fn(), loadPersonalKey: vi.fn(),
  getLocalLtxSubmissionByRequestId: vi.fn(), createOrReuseLocalLtxTask: vi.fn(),
  createImageToVideo: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.userFromRequest }));
vi.mock("@/lib/user-provider-credentials", () => ({ loadPersonalKey: mocks.loadPersonalKey }));
vi.mock("@/lib/ltx-task-coordinator", () => ({ getLocalLtxSubmissionByRequestId: mocks.getLocalLtxSubmissionByRequestId, createOrReuseLocalLtxTask: mocks.createOrReuseLocalLtxTask, LtxTaskSubmissionPendingError: class extends Error {} }));
vi.mock("@/lib/video-generation-provider", () => ({ createImageToVideo: mocks.createImageToVideo, isVideoGenerationProviderError: () => false }));
import { GET, POST } from "./route";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.userFromRequest.mockResolvedValue({ issuer: "issuer", subject: "alice" });
  mocks.loadPersonalKey.mockResolvedValue("personal-key");
});

describe("personal video generation access", () => {
  it("requires login for status and submission", async () => {
    mocks.userFromRequest.mockResolvedValue(null);
    expect((await GET(new NextRequest("http://localhost/api/user/video-generation"))).status).toBe(401);
    const request = new NextRequest("http://localhost/api/user/video-generation", { method: "POST", headers: { Origin: "http://localhost", "Content-Length": "100" }, body: new FormData() });
    expect((await POST(request)).status).toBe(401);
  });

  it("does not reveal another user's task by request ID", async () => {
    mocks.getLocalLtxSubmissionByRequestId.mockReturnValue({ visualIdentityId: "user-upload:issuer#bob" });
    const request = new NextRequest("http://localhost/api/user/video-generation?request_id=11111111-1111-4111-8111-111111111111");
    expect((await GET(request)).status).toBe(404);
  });

  it("requires same-origin submission and a personal key", async () => {
    const crossOrigin = new NextRequest("http://localhost/api/user/video-generation", { method: "POST", headers: { Origin: "https://evil.example", "Content-Length": "100" }, body: new FormData() });
    expect((await POST(crossOrigin)).status).toBe(403);
    mocks.loadPersonalKey.mockResolvedValue(null);
    const sameOrigin = new NextRequest("http://localhost/api/user/video-generation", { method: "POST", headers: { Origin: "http://localhost", "Content-Length": "100" }, body: new FormData() });
    expect((await POST(sameOrigin)).status).toBe(409);
  });

  it("records the authenticated owner on a paid task", async () => {
    const image = new Uint8Array(128);
    image.set([137, 80, 78, 71, 13, 10, 26, 10]);
    const form = new FormData();
    form.set("image", new File([image], "portrait.png", { type: "image/png" }));
    form.set("prompt", "A gentle head turn");
    form.set("requestId", "11111111-1111-4111-8111-111111111111");
    form.set("rightsConfirmed", "true");
    form.set("creditsAccepted", "true");
    mocks.createOrReuseLocalLtxTask.mockResolvedValue({ task: { taskId: "provider-task", state: "processing" }, reused: false });
    const request = new NextRequest("http://localhost/api/user/video-generation", { method: "POST", headers: { Origin: "http://localhost", "Content-Length": "1000" }, body: form });
    const response = await POST(request);
    expect(response.status).toBe(202);
    expect(mocks.createOrReuseLocalLtxTask).toHaveBeenCalledWith(expect.objectContaining({ visualIdentityId: "user-upload:issuer#alice", model: "MiniMax-H3", duration: 4 }), expect.any(Function), expect.objectContaining({ requestId: "11111111-1111-4111-8111-111111111111" }));
  });

  it("rejects a one-second paid request before calling MiniMax", async () => {
    const form = new FormData();
    form.set("duration", "1");
    const request = new NextRequest("http://localhost/api/user/video-generation", { method: "POST", headers: { Origin: "http://localhost", "Content-Length": "1000" }, body: form });
    expect((await POST(request)).status).toBe(400);
    expect(mocks.createOrReuseLocalLtxTask).not.toHaveBeenCalled();
  });
});
