import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({
  userFromRequest: vi.fn(), loadPersonalKey: vi.fn(), getTrustedLocalLtxTask: vi.fn(),
  getVideoGeneration: vi.fn(), releaseLocalLtxTask: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.userFromRequest }));
vi.mock("@/lib/user-provider-credentials", () => ({ loadPersonalKey: mocks.loadPersonalKey }));
vi.mock("@/lib/ltx-task-coordinator", () => ({ getTrustedLocalLtxTask: mocks.getTrustedLocalLtxTask, releaseLocalLtxTask: mocks.releaseLocalLtxTask }));
vi.mock("@/lib/video-generation-provider", () => ({ getVideoGeneration: mocks.getVideoGeneration, isVideoGenerationProviderError: () => false }));
import { GET } from "./route";
import { providerKeyFingerprint } from "@/lib/provider-api-key";

const request = new NextRequest("http://localhost/api/user/video-generation/provider-task");
const context = { params: Promise.resolve({ taskId: "provider-task" }) };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.userFromRequest.mockResolvedValue({ issuer: "issuer", subject: "alice" });
  mocks.loadPersonalKey.mockResolvedValue("personal-key");
  mocks.getTrustedLocalLtxTask.mockReturnValue({ visualIdentityId: "user-upload:issuer#alice", model: "MiniMax-H3", credentialFingerprint: providerKeyFingerprint("personal-key") });
});

describe("personal video task access", () => {
  it("hides another user's task", async () => {
    mocks.getTrustedLocalLtxTask.mockReturnValue({ visualIdentityId: "user-upload:issuer#bob", model: "MiniMax-H3" });
    expect((await GET(request, context)).status).toBe(404);
    expect(mocks.getVideoGeneration).not.toHaveBeenCalled();
  });
  it("rejects access after the personal Key changes", async () => {
    mocks.loadPersonalKey.mockResolvedValue("changed-key");
    expect((await GET(request, context)).status).toBe(403);
  });
  it("returns a scoped result URL after provider success", async () => {
    mocks.getVideoGeneration.mockResolvedValue({ taskId: "provider-task", state: "success" });
    const response = await GET(request, context);
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ result_url: "/api/user/video-generation/provider-task/result" });
    expect(mocks.releaseLocalLtxTask).toHaveBeenCalledWith("provider-task", "success");
  });
});
