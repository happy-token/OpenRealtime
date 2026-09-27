import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ user: vi.fn(), avatar: vi.fn(), job: vi.fn(), start: vi.fn(), resume: vi.fn(), builtIn: vi.fn() }));
vi.mock("./user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("./personal-avatar-library", () => ({ findPersonalAvatar: dependencies.avatar }));
vi.mock("./personal-talking-worker", () => ({ getPersonalTalkingJob: dependencies.job, startPersonalTalkingJob: dependencies.start, resumePersonalTalkingJob: dependencies.resume }));
vi.mock("./talking-reference-audio", () => ({ readBuiltInTalkingAudio: dependencies.builtIn }));

import { getPersonalTalking, postPersonalTalking } from "./personal-talking-api";

const user = { issuer: "https://issuer.example", subject: "alice" };
const context = { params: Promise.resolve({ avatarId: "avatar-personal-1", avatarActionId: "motion-1" }) };
const avatar = { deletedAt: null, actions: [{ avatar_action_id: "motion-1", video_url: "/api/user/motion-assets/a?preview=1", deleted_at: null }] };
function request(method: "GET" | "POST", form?: FormData, origin = "http://localhost:3010") {
  return new Request("http://localhost:3010/api/user/avatars/avatar-personal-1/actions/motion-1/talking-variants/generate", {
    method, headers: { origin }, ...(form ? { body: form } : {}),
  });
}

describe("personal talking API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dependencies.user.mockResolvedValue(user);
    dependencies.avatar.mockResolvedValue(avatar);
    dependencies.job.mockResolvedValue(null);
    dependencies.start.mockResolvedValue({ id: "musetalk-job", state: "queued" });
    dependencies.resume.mockResolvedValue({ id: "musetalk-job", state: "queued" });
    dependencies.builtIn.mockResolvedValue(Buffer.from("RIFFexampleWAVE"));
  });

  it("requires login and ownership before reading a job", async () => {
    dependencies.user.mockResolvedValueOnce(null);
    expect((await getPersonalTalking(request("GET"), context, "musetalk")).status).toBe(401);
    dependencies.avatar.mockResolvedValueOnce(null);
    expect((await getPersonalTalking(request("GET"), context, "musetalk")).status).toBe(404);
    expect(dependencies.job).not.toHaveBeenCalled();
  });

  it("rejects cross-origin generation and another user's avatar", async () => {
    expect((await postPersonalTalking(request("POST", new FormData(), "http://evil.example"), context, "musetalk")).status).toBe(403);
    dependencies.avatar.mockResolvedValueOnce(null);
    expect((await postPersonalTalking(request("POST", new FormData()), context, "musetalk")).status).toBe(404);
    expect(dependencies.start).not.toHaveBeenCalled();
  });

  it("starts MuseTalk only with the authenticated user's asset", async () => {
    const response = await postPersonalTalking(request("POST", new FormData()), context, "musetalk");
    expect(response.status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith(expect.objectContaining({ user, kind: "musetalk", avatarId: "avatar-personal-1", actionId: "motion-1" }));
  });

  it("requires Wav2Lip reference audio and non-commercial consent", async () => {
    expect((await postPersonalTalking(request("POST", new FormData()), context, "wav2lip")).status).toBe(400);
    const form = new FormData();
    form.set("audioSource", "builtin");
    form.set("rightsConfirmed", "true");
    form.set("usageScope", "internal_evaluation");
    dependencies.start.mockResolvedValueOnce({ id: "wav2lip-job", state: "queued" });
    expect((await postPersonalTalking(request("POST", form), context, "wav2lip")).status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith(expect.objectContaining({ kind: "wav2lip", rightsConfirmed: true, usageScope: "internal_evaluation" }));
  });

  it("recovers a failed remote job with the same job ID", async () => {
    dependencies.job.mockResolvedValueOnce({ id: "musetalk-job", state: "failed", retryBlocked: true });
    const response = await postPersonalTalking(request("POST", new FormData()), context, "musetalk");
    expect(response.status).toBe(202);
    expect(dependencies.resume).toHaveBeenCalledWith(user, "musetalk", "avatar-personal-1", "motion-1");
    expect(dependencies.start).not.toHaveBeenCalled();
  });
});
