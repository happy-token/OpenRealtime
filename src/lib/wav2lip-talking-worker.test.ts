import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const repository = vi.hoisted(() => ({ findOwnedAvatar: vi.fn(), attachTalkingVariant: vi.fn() }));
vi.mock("./avatar-catalog-repository", () => repository);
import { acceptWav2LipJob, getWav2LipJob, startWav2LipJob } from "./wav2lip-talking-worker";

let root: string;
beforeEach(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-wav2lip-"));
  vi.stubEnv("WAV2LIP_JOB_ROOT", root);
  vi.clearAllMocks();
});
afterEach(async () => { vi.unstubAllEnvs(); await rm(root, { recursive: true, force: true }); });

describe("Wav2Lip talking jobs", () => {
  it("keeps a completed preview unbound until acceptance", async () => {
    const id = "wav2lip-22222222-2222-4222-8222-222222222222";
    const variant = { id, method: "wav2lip", source_video_url: "/digital-human/source.mp4", video_url: `/digital-human/talking-variants/${id}.mp4` };
    const media = path.join(process.cwd(), "public", "digital-human", "talking-variants", `${id}.mp4`);
    await mkdir(path.dirname(media), { recursive: true });
    await writeFile(media, "preview");
    await mkdir(path.join(root, id));
    await writeFile(path.join(root, id, "job.json"), JSON.stringify({ id, state: "ready_for_review", avatarId: "avatar-review", actionId: "action-review", sourceUrl: variant.source_video_url, createdAt: "2026-09-23T00:00:00.000Z", updatedAt: "2026-09-23T00:00:00.000Z", variant }));
    repository.attachTalkingVariant.mockResolvedValue({ avatar_action_id: "action-review", talking_variants: [variant] });
    expect((await getWav2LipJob("avatar-review", "action-review"))?.state).toBe("ready_for_review");
    expect(repository.attachTalkingVariant).not.toHaveBeenCalled();
    await expect(acceptWav2LipJob("avatar-review", "action-review", id)).resolves.toMatchObject({ job: { state: "success" } });
    expect(repository.attachTalkingVariant).toHaveBeenCalledWith("avatar-review", "action-review", variant);
    await rm(media, { force: true });
  });
  const audio = new File([new Uint8Array(101)], "sample.wav", { type: "audio/wav" });
  it("requires rights and non-commercial scope before accepting media", async () => {
    const input = { avatarId: "avatar-a", actionId: "action-a", audio, rightsConfirmed: false, usageScope: "internal_evaluation" };
    await expect(startWav2LipJob(input)).rejects.toThrow("使用权");
    await expect(startWav2LipJob({ ...input, rightsConfirmed: true, usageScope: "commercial" })).rejects.toThrow("非商业");
  });
  it("reuses a saved variant only for the current action source", async () => {
    const variant = { id: "wav2lip-existing", method: "wav2lip", source_video_url: "/digital-human/source.mp4" };
    repository.findOwnedAvatar.mockResolvedValue({ actions: [{ avatar_action_id: "action-a", video_url: variant.source_video_url, talking_variants: [variant] }] });
    await expect(startWav2LipJob({ avatarId: "avatar-a", actionId: "action-a", audio, rightsConfirmed: true, usageScope: "internal_evaluation" })).resolves.toMatchObject({ state: "success", variant });
  });
  it("coalesces concurrent starts for the same action", async () => {
    const variant = { id: "wav2lip-existing", method: "wav2lip", source_video_url: "/digital-human/source.mp4" };
    repository.findOwnedAvatar.mockImplementation(async () => {
      await new Promise(resolve => setTimeout(resolve, 5));
      return { actions: [{ avatar_action_id: "action-c", video_url: variant.source_video_url, talking_variants: [variant] }] };
    });
    const input = { avatarId: "avatar-c", actionId: "action-c", audio, rightsConfirmed: true, usageScope: "internal_evaluation" };
    const [first, second] = await Promise.all([startWav2LipJob(input), startWav2LipJob(input)]);
    expect(first).toEqual(second);
    expect(repository.findOwnedAvatar).toHaveBeenCalledTimes(1);
  });
  it("marks interrupted jobs failed so users can submit again", async () => {
    const id = "wav2lip-11111111-1111-4111-8111-111111111111";
    await mkdir(path.join(root, id));
    await writeFile(path.join(root, id, "job.json"), JSON.stringify({ id, state: "processing", avatarId: "avatar-b", actionId: "action-b", sourceUrl: "/digital-human/source.mp4", createdAt: "2026-09-12T10:00:00.000Z", updatedAt: "2026-09-12T10:00:00.000Z" }));
    await expect(getWav2LipJob("avatar-b", "action-b")).resolves.toMatchObject({ state: "failed", error: expect.stringContaining("重新提交") });
  });
});
