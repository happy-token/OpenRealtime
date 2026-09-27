import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ avatar: vi.fn(), service: vi.fn(), probe: vi.fn(), motion: vi.fn() }));
vi.mock("./personal-avatar-library", () => ({ findPersonalAvatar: dependencies.avatar, attachPersonalTalkingVariant: vi.fn() }));
vi.mock("./user-talking-model-services", () => ({ loadUserTalkingService: dependencies.service }));
vi.mock("./model-service-connections", () => ({ probeModelService: dependencies.probe }));
vi.mock("./personal-motion-library", async (importOriginal) => ({ ...await importOriginal<typeof import("./personal-motion-library")>(), readPersonalMotionVideo: dependencies.motion }));

import { getPersonalTalkingJob, startPersonalTalkingJob } from "./personal-talking-worker";
import { personalLibraryOwnerDir } from "./personal-motion-library";

const alice = { issuer: "https://issuer.example", subject: "alice" };
const bob = { issuer: "https://issuer.example", subject: "bob" };
const sourceUrl = `/api/user/motion-assets/${"a".repeat(64)}?preview=1`;
let directory: string;

describe("personal talking worker isolation", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    directory = await mkdtemp(path.join(os.tmpdir(), "personal-talking-test-"));
    vi.stubEnv("OPENREALTIME_PERSONAL_MOTION_PATH", directory);
    dependencies.avatar.mockResolvedValue({ deletedAt: null, createdAt: "2026-01-01", updatedAt: "2026-01-01", actions: [{ avatar_action_id: "action-1", video_url: sourceUrl, deleted_at: null, talking_variants: [] }] });
    dependencies.service.mockResolvedValue(null);
  });
  afterEach(async () => {
    vi.unstubAllEnvs();
    await rm(directory, { recursive: true, force: true });
  });

  it("rejects another user's avatar before accessing any service", async () => {
    dependencies.avatar.mockResolvedValueOnce(null);
    await expect(startPersonalTalkingJob({ user: alice, kind: "musetalk", avatarId: "avatar-personal-1", actionId: "action-1" })).rejects.toThrow("找不到可用的个人动作底片");
    expect(dependencies.service).not.toHaveBeenCalled();
  });

  it("never falls back to a platform service for an unconfigured user", async () => {
    await expect(startPersonalTalkingJob({ user: alice, kind: "musetalk", avatarId: "avatar-personal-1", actionId: "action-1" })).rejects.toThrow("个人服务尚未配置");
    expect(dependencies.service).toHaveBeenCalledWith(alice, "musetalk");
  });

  it("requires non-commercial rights and audio for Wav2Lip", async () => {
    await expect(startPersonalTalkingJob({ user: alice, kind: "wav2lip", avatarId: "avatar-personal-1", actionId: "action-1" })).rejects.toThrow("非商业用途");
    await expect(startPersonalTalkingJob({ user: alice, kind: "wav2lip", avatarId: "avatar-personal-1", actionId: "action-1", audio: Buffer.from("audio"), rightsConfirmed: true, usageScope: "commercial" })).rejects.toThrow("非商业用途");
    expect(dependencies.service).not.toHaveBeenCalled();
  });

  it("loads persisted jobs only from the requesting user's private directory", async () => {
    const job = { id: "musetalk-12345678-1234-1234-1234-123456789abc", kind: "musetalk", state: "ready_for_review", avatarId: "avatar-personal-1", actionId: "action-1", sourceUrl, createdAt: "2026-01-01", updatedAt: "2026-01-01" };
    const jobDir = path.join(personalLibraryOwnerDir(alice), "talking-jobs", job.id);
    await mkdir(jobDir, { recursive: true });
    await writeFile(path.join(jobDir, "job.json"), JSON.stringify(job));
    expect((await getPersonalTalkingJob(alice, "musetalk", "avatar-personal-1", "action-1"))?.id).toBe(job.id);
    expect(await getPersonalTalkingJob(bob, "musetalk", "avatar-personal-1", "action-1")).toBeNull();
  });
});
