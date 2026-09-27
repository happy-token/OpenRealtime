import { describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ user: vi.fn(), avatar: vi.fn(), lip: vi.fn(), personal: vi.fn() }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/personal-avatar-library", () => ({ findPersonalAvatar: dependencies.avatar }));
vi.mock("@/lib/lipforcing-talking-worker", () => ({ acceptLipForcingJob: dependencies.lip }));
vi.mock("@/lib/personal-talking-worker", () => ({ acceptPersonalTalkingJob: dependencies.personal }));

import { POST } from "./route";

const user = { issuer: "issuer", subject: "alice" };
const context = { params: Promise.resolve({ avatarId: "avatar-personal-1", avatarActionId: "action-1" }) };
function request(jobId: string) {
  return new Request("http://localhost:3010/api/user/avatars/avatar-personal-1/actions/action-1/talking-variants/accept", {
    method: "POST", headers: { origin: "http://localhost:3010", "content-type": "application/json" }, body: JSON.stringify({ jobId }),
  });
}

describe("personal talking acceptance", () => {
  it.each(["musetalk", "wav2lip"])("keeps %s acceptance under the user's avatar", async (kind) => {
    vi.clearAllMocks();
    dependencies.user.mockResolvedValue(user);
    dependencies.avatar.mockResolvedValue({ deletedAt: null, actions: [{ avatar_action_id: "action-1", deleted_at: null }] });
    dependencies.personal.mockResolvedValue({ action: { avatar_action_id: "action-1" } });
    const id = `${kind}-12345678-1234-1234-1234-123456789abc`;
    expect((await POST(request(id), context)).status).toBe(200);
    expect(dependencies.personal).toHaveBeenCalledWith(user, kind, "avatar-personal-1", "action-1", id);
    expect(dependencies.lip).not.toHaveBeenCalled();
  });

  it("does not accept a job for another user's avatar", async () => {
    vi.clearAllMocks();
    dependencies.user.mockResolvedValue(user);
    dependencies.avatar.mockResolvedValue(null);
    expect((await POST(request("musetalk-12345678-1234-1234-1234-123456789abc"), context)).status).toBe(404);
    expect(dependencies.personal).not.toHaveBeenCalled();
  });
});
