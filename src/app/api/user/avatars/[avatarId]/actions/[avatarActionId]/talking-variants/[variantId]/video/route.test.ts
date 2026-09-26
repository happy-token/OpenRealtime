import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ user: vi.fn(), avatar: vi.fn(), job: vi.fn(), output: vi.fn(), read: vi.fn(), stat: vi.fn() }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/personal-avatar-library", () => ({ findPersonalAvatar: dependencies.avatar }));
vi.mock("@/lib/lipforcing-talking-worker", () => ({ getLipForcingJob: dependencies.job, privateLipForcingOutput: dependencies.output }));
vi.mock("node:fs/promises", () => ({ readFile: dependencies.read, stat: dependencies.stat }));

import { GET } from "./route";

const id = "lipforcing-12345678-1234-1234-1234-123456789abc";
const context = { params: Promise.resolve({ avatarId: "avatar-personal-123", avatarActionId: "motion-123", variantId: id }) };

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.user.mockResolvedValue({ issuer: "test", subject: "alice" });
  dependencies.avatar.mockResolvedValue({ deletedAt: null, actions: [{ avatar_action_id: "motion-123", deleted_at: null }] });
  dependencies.job.mockResolvedValue({ id, state: "ready_for_review" });
  dependencies.output.mockReturnValue("/private/video.mp4");
  dependencies.stat.mockResolvedValue({ isFile: () => true, size: 8 });
  dependencies.read.mockResolvedValue(Buffer.from("12345678"));
});

describe("private Lip Forcing preview", () => {
  it("does not read a video for another user's avatar", async () => {
    dependencies.avatar.mockResolvedValue(null);
    expect((await GET(new Request("http://localhost/video"), context)).status).toBe(404);
    expect(dependencies.output).not.toHaveBeenCalled();
    expect(dependencies.read).not.toHaveBeenCalled();
  });

  it("supports authenticated range requests for the owner", async () => {
    const response = await GET(new Request("http://localhost/video", { headers: { Range: "bytes=2-5" } }), context);
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 2-5/8");
    expect(await response.text()).toBe("3456");
  });
});
