import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({
  authorized: vi.fn(), job: vi.fn(), start: vi.fn(), resume: vi.fn(), personal: vi.fn(), shared: vi.fn(), user: vi.fn(), signature: vi.fn(), builtInAudio: vi.fn(),
}));
vi.mock("@/lib/avatar-assets-server", () => ({
  authorizeAvatarAssetRequest: dependencies.authorized,
  validAvatarAssetId: (id: unknown) => typeof id === "string" && /^[A-Za-z0-9-]+$/.test(id),
  jsonError: (error: string, status: number) => Response.json({ error }, { status }),
}));
vi.mock("@/lib/lipforcing-talking-worker", () => ({ getLipForcingJob: dependencies.job, startLipForcingJob: dependencies.start, resumeLipForcingJob: dependencies.resume }));
vi.mock("@/lib/personal-role-library", () => ({ findPersonalRole: dependencies.personal }));
vi.mock("@/lib/role-catalog-repository", () => ({ findRole: dependencies.shared }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/media-signatures", () => ({ hasMatchingAudioSignature: dependencies.signature }));
vi.mock("@/lib/talking-reference-audio", () => ({ readBuiltInTalkingAudio: dependencies.builtInAudio }));

import { POST } from "./route";

const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "action-123" }) };
function request(roleId: string) {
  const form = new FormData();
  form.set("roleId", roleId);
  return new Request("http://localhost:3010/api/avatars/avatar-123/actions/action-123/talking-variants/generate-lipforcing", {
    method: "POST", body: form, headers: { origin: "http://localhost:3010" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.authorized.mockReturnValue(true);
  dependencies.job.mockResolvedValue(null);
  dependencies.start.mockResolvedValue({ id: "lipforcing-123", state: "queued" });
  dependencies.resume.mockResolvedValue({ id: "lipforcing-123", state: "processing" });
  dependencies.user.mockResolvedValue({ issuer: "test", subject: "user-one" });
  dependencies.signature.mockReturnValue(true);
  dependencies.builtInAudio.mockResolvedValue(Buffer.from("builtin reference"));
});

describe("Lip Forcing generation submission", () => {
  it("resumes a failed GPU job with the same ID instead of submitting a new one", async () => {
    dependencies.job.mockResolvedValue({ id: "lipforcing-123", state: "failed", retryBlocked: true });
    const response = await POST(request("unused-role"), context);
    expect(response.status).toBe(202);
    expect(dependencies.resume).toHaveBeenCalledWith("avatar-123", "action-123");
    expect(dependencies.start).not.toHaveBeenCalled();
  });
  it("uses built-in audio when no role or upload is selected", async () => {
    const form = new FormData();
    form.set("audioSource", "builtin");
    const response = await POST(new Request("http://localhost:3010/api/avatars/avatar-123/actions/action-123/talking-variants/generate-lipforcing", { method: "POST", body: form }), context);
    expect(response.status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith("avatar-123", "action-123", Buffer.from("builtin reference"));
  });
  it("uses the selected role's voice for the reference and queues its action", async () => {
    dependencies.personal.mockResolvedValue({ role_id: "role-personal-123", avatar_id: "avatar-123", voice_provider: "doubao", voice_id: "voice-123" });
    const audio = new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]);
    const fetcher = vi.fn().mockResolvedValue(new Response(audio, { headers: { "content-type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(request("role-personal-123"), context);
    expect(response.status).toBe(202);
    expect(dependencies.personal).toHaveBeenCalledWith({ issuer: "test", subject: "user-one" }, "role-personal-123");
    expect(String(fetcher.mock.calls[0][0])).toContain("voice=voice-123");
    expect(dependencies.start).toHaveBeenCalledWith("avatar-123", "action-123", Buffer.from(audio));
    vi.unstubAllGlobals();
  });

  it("rejects a role bound to another avatar before requesting TTS", async () => {
    dependencies.shared.mockResolvedValue({ role_id: "role-shared", avatar_id: "avatar-other", voice_provider: "doubao", voice_id: "voice-123" });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await POST(request("role-shared"), context)).status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
    expect(dependencies.start).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
