import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({
  userFromRequest: vi.fn(), getTrustedLocalLtxTask: vi.fn(),
  loadPersonalKey: vi.fn(), getVideoGeneration: vi.fn(),
  downloadLtxResultVideo: vi.fn(), savePersonalMotion: vi.fn(), listPersonalMotions: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.userFromRequest }));
vi.mock("@/lib/ltx-task-coordinator", () => ({ getTrustedLocalLtxTask: mocks.getTrustedLocalLtxTask }));
vi.mock("@/lib/user-provider-credentials", () => ({ loadPersonalKey: mocks.loadPersonalKey }));
vi.mock("@/lib/video-generation-provider", () => ({ getVideoGeneration: mocks.getVideoGeneration, isVideoGenerationProviderError: () => false }));
vi.mock("@/lib/ltx-result-video", () => ({ downloadLtxResultVideo: mocks.downloadLtxResultVideo }));
vi.mock("@/lib/personal-motion-library", () => ({ savePersonalMotion: mocks.savePersonalMotion, listPersonalMotions: mocks.listPersonalMotions }));

import { GET, POST } from "./route";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.userFromRequest.mockResolvedValue({ issuer: "issuer", subject: "alice" });
  mocks.listPersonalMotions.mockResolvedValue([]);
});

describe("personal motion asset access", () => {
  it("requires a session to list or save", async () => {
    mocks.userFromRequest.mockResolvedValue(null);
    expect((await GET(new NextRequest("http://localhost/api/user/motion-assets"))).status).toBe(401);
    const request = new NextRequest("http://localhost/api/user/motion-assets", { method: "POST", headers: { Origin: "http://localhost" }, body: JSON.stringify({ taskId: "task-123456" }) });
    expect((await POST(request)).status).toBe(401);
  });

  it("does not query a task owned by another user", async () => {
    mocks.getTrustedLocalLtxTask.mockReturnValue({ visualIdentityId: "user-upload:issuer#bob", model: "MiniMax-H3" });
    const request = new NextRequest("http://localhost/api/user/motion-assets", { method: "POST", headers: { Origin: "http://localhost" }, body: JSON.stringify({ taskId: "task-123456" }) });
    expect((await POST(request)).status).toBe(404);
    expect(mocks.getVideoGeneration).not.toHaveBeenCalled();
    expect(mocks.savePersonalMotion).not.toHaveBeenCalled();
  });
});
