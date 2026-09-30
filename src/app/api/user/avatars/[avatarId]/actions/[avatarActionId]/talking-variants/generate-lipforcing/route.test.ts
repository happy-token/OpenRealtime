import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ origin: vi.fn(), user: vi.fn(), avatar: vi.fn(), role: vi.fn(), job: vi.fn(), start: vi.fn(), resume: vi.fn(), signature: vi.fn(), builtInAudio: vi.fn() }));
vi.mock("@/lib/avatar-test-access", () => ({ isSameOriginAvatarMutation: dependencies.origin }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/personal-avatar-library", () => ({ findPersonalAvatar: dependencies.avatar }));
vi.mock("@/lib/personal-role-library", () => ({ findPersonalRole: dependencies.role }));
vi.mock("@/lib/lipforcing-talking-worker", () => ({ getLipForcingJob: dependencies.job, startLipForcingJob: dependencies.start, resumeLipForcingJob: dependencies.resume }));
vi.mock("@/lib/media-signatures", () => ({ hasMatchingAudioSignature: dependencies.signature }));
vi.mock("@/lib/talking-reference-audio", () => ({ readBuiltInTalkingAudio: dependencies.builtInAudio }));

import { GET, POST } from "./route";

const user = { issuer: "test", subject: "alice" };
const context = { params: Promise.resolve({ avatarId: "avatar-personal-123", avatarActionId: "motion-123" }) };
function request(roleId = "role-personal-123") {
  const form = new FormData();
  form.set("roleId", roleId);
  return new Request("http://localhost:3010/api/user/avatars/avatar-personal-123/actions/motion-123/talking-variants/generate-lipforcing", { method: "POST", body: form, headers: { origin: "http://localhost:3010" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.origin.mockReturnValue(true);
  dependencies.user.mockResolvedValue(user);
  dependencies.avatar.mockResolvedValue({ id: "avatar-personal-123", deletedAt: null, actions: [{ avatar_action_id: "motion-123", video_url: "/api/user/motion-assets/abc?preview=1", deleted_at: null }] });
  dependencies.role.mockResolvedValue({ avatar_id: "avatar-personal-123", voice_provider: "doubao", voice_id: "voice-123" });
  dependencies.job.mockResolvedValue(null);
  dependencies.start.mockResolvedValue({ id: "lipforcing-job", state: "queued" });
  dependencies.resume.mockResolvedValue({ id: "lipforcing-job", state: "processing" });
  dependencies.signature.mockReturnValue(true);
  dependencies.builtInAudio.mockResolvedValue(Buffer.from("builtin wav"));
});

describe("personal Lip Forcing generation", () => {
  it("uses built-in reference audio when the resource library has no role", async () => {
    const form = new FormData();
    form.set("audioSource", "builtin");
    const response = await POST(new Request("http://localhost:3010", { method: "POST", body: form, headers: { origin: "http://localhost:3010" } }), context);
    expect(response.status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith("avatar-personal-123", "motion-123", Buffer.from("builtin wav"), user);
    expect(dependencies.role).not.toHaveBeenCalled();
  });
  it("resumes the current owner's failed GPU job without a new submission", async () => {
    dependencies.job.mockResolvedValue({ id: "lipforcing-job", state: "failed", retryBlocked: true });
    expect((await POST(request(), context)).status).toBe(202);
    expect(dependencies.resume).toHaveBeenCalledWith("avatar-personal-123", "motion-123", user);
    expect(dependencies.start).not.toHaveBeenCalled();
  });
  it("rejects a request for another user's avatar before reading any job", async () => {
    dependencies.avatar.mockResolvedValue(null);
    expect((await GET(new Request("http://localhost:3010"), context)).status).toBe(404);
    expect((await POST(request(), context)).status).toBe(404);
    expect(dependencies.job).not.toHaveBeenCalled();
  });

  it("uses the current user's role voice and passes owner scope to the worker", async () => {
    const audio = new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]);
    const fetcher = vi.fn().mockResolvedValue(new Response(audio, { headers: { "content-type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetcher);
    try {
      expect((await POST(request(), context)).status).toBe(202);
      expect(dependencies.role).toHaveBeenCalledWith(user, "role-personal-123");
      expect(dependencies.start).toHaveBeenCalledWith("avatar-personal-123", "motion-123", Buffer.from(audio), user);
    } finally { vi.unstubAllGlobals(); }
  });

  it("rejects a role using a different avatar", async () => {
    dependencies.role.mockResolvedValue({ avatar_id: "avatar-personal-other", voice_provider: "doubao", voice_id: "voice-123" });
    expect((await POST(request(), context)).status).toBe(400);
    expect(dependencies.start).not.toHaveBeenCalled();
  });
});
