import { beforeEach, describe, expect, it, vi } from "vitest";
const repository = vi.hoisted(() => ({ findOwnedAvatar: vi.fn(), attachTalkingVariant: vi.fn() }));
vi.mock("./avatar-catalog-repository", () => repository);
import { acceptTalkingJob, readTalkingSource, startTalkingJob } from "./musetalk-talking-worker";
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

describe("MuseTalk durable job recovery", () => {
  it("attaches a preview only after explicit acceptance", async () => {
    const { mkdtemp, mkdir, writeFile, rm } = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    const root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-musetalk-review-"));
    vi.stubEnv("MUSETALK_JOB_ROOT", root);
    const id = "musetalk-22222222-2222-4222-8222-222222222222";
    const variant = { id, method: "musetalk", source_video_url: "/digital-human/action.mp4", video_url: `/digital-human/talking-variants/${id}.mp4` };
    const media = path.join(process.cwd(), "public", "digital-human", "talking-variants", `${id}.mp4`);
    await mkdir(path.dirname(media), { recursive: true });
    await writeFile(media, "preview");
    await mkdir(path.join(root, id));
    await writeFile(path.join(root, id, "job.json"), JSON.stringify({ id, state: "ready_for_review", avatarId: "avatar-review", actionId: "action-review", variant }));
    repository.attachTalkingVariant.mockResolvedValue({ avatar_action_id: "action-review", talking_variants: [variant] });
    await expect(acceptTalkingJob("avatar-review", "action-review", id)).resolves.toMatchObject({ job: { state: "success" } });
    expect(repository.attachTalkingVariant).toHaveBeenCalledWith("avatar-review", "action-review", variant);
    await expect(acceptTalkingJob("avatar-review", "action-review", id)).rejects.toThrow("待确认");
    vi.unstubAllEnvs();
    await rm(media, { force: true });
    await rm(root, { recursive: true, force: true });
  });
  it("recovers an interrupted job as retry-blocked after process memory loss", async () => {
    const { mkdtemp, mkdir, writeFile, rm } = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    const root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-musetalk-"));
    vi.stubEnv("MUSETALK_JOB_ROOT", root);
    const id = "musetalk-11111111-1111-4111-8111-111111111111";
    await mkdir(path.join(root, id));
    await writeFile(path.join(root, id, "job.json"), JSON.stringify({
      id,
      state: "processing",
      avatarId: "avatar-1",
      actionId: "action-1",
      sourceUrl: "/digital-human/action.mp4",
      createdAt: "2026-09-12T10:00:00.000Z",
      updatedAt: "2026-09-12T10:01:00.000Z",
    }));
    const { getTalkingJob } = await import("./musetalk-talking-worker");
    await expect(getTalkingJob("avatar-1", "action-1")).resolves.toMatchObject({
      state: "failed",
      retryBlocked: true,
      error: expect.stringContaining("避免重复消耗 GPU"),
    });
    vi.unstubAllEnvs();
    await rm(root, { recursive: true, force: true });
  });
});
