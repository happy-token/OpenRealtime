import { beforeEach, describe, expect, it, vi } from "vitest";
const repository = vi.hoisted(() => ({ findOwnedAvatar: vi.fn(), attachTalkingVariant: vi.fn() }));
vi.mock("./avatar-catalog-repository", () => repository);
import { readTalkingSource, startTalkingJob } from "./musetalk-talking-worker";
beforeEach(() => vi.clearAllMocks());
describe("MuseTalk source generation", () => {
  it.each(["https://example.com/video.mp4", "http://127.0.0.1/secret", "/api/avatars/private/image", "/digital-human/../../.env", "/digital-human/a.mp4?url=x"])("rejects unsupported or escaping source %s", async source => {
    await expect(readTalkingSource(source)).rejects.toThrow();
  });
  it("reuses a completed variant only for the current source", async () => {
    const variant = { id: "muse-existing", method: "musetalk", source_video_url: "/idle.mp4" };
    repository.findOwnedAvatar.mockResolvedValue({ actions: [{ avatar_action_id: "base", video_url: "/idle.mp4", talking_variants: [variant] }] });
    expect(await startTalkingJob("avatar-test", "base")).toEqual({ id: "muse-existing", state: "success", variant });
  });
  it("does not queue deleted or missing actions", async () => {
    repository.findOwnedAvatar.mockResolvedValue({ actions: [{ avatar_action_id: "base", video_url: "/idle.mp4", deleted_at: "today" }] });
    await expect(startTalkingJob("avatar-test", "base")).rejects.toThrow("找不到");
  });
});
