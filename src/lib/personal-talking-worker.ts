import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import type { AvatarTalkingVariant } from "./avatar-records";
import { runInferenceServiceJob } from "./lipforcing-service-client";
import { probeModelService } from "./model-service-connections";
import { attachPersonalTalkingVariant, findPersonalAvatar } from "./personal-avatar-library";
import { personalLibraryOwnerDir, readPersonalMotionVideo } from "./personal-motion-library";
import { loadUserTalkingService, type PersonalTalkingKind } from "./user-talking-model-services";
import type { WebUser } from "./user-session";

const run = promisify(execFile);
const JOB_ID = /^(musetalk|wav2lip)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_AUDIO_BYTES = 20 * 1024 * 1024;
type State = "queued" | "processing" | "ready_for_review" | "success" | "failed";
export type PersonalTalkingJob = {
  id: string; kind: PersonalTalkingKind; state: State; avatarId: string; actionId: string;
  sourceUrl: string; createdAt: string; updatedAt: string; retryBlocked?: boolean;
  usageScope?: string; error?: string; variant?: AvatarTalkingVariant;
};
type Store = { jobs: Map<string, PersonalTalkingJob>; pending: Map<string, Promise<PersonalTalkingJob>>; tail: Promise<void> };
const globalStore = globalThis as typeof globalThis & { __personalTalkingJobs?: Store };
const store = globalStore.__personalTalkingJobs ??= { jobs: new Map(), pending: new Map(), tail: Promise.resolve() };

function root(user: WebUser) { return path.join(personalLibraryOwnerDir(user), "talking-jobs"); }
function key(user: WebUser, kind: PersonalTalkingKind, avatarId: string, actionId: string) {
  return `${personalLibraryOwnerDir(user)}/${kind}/${avatarId}/${actionId}`;
}
function jobDir(user: WebUser, id: string) { return path.join(root(user), id); }

async function persist(user: WebUser, job: PersonalTalkingJob) {
  const directory = jobDir(user, job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = path.join(directory, `job.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job), { flag: "wx", mode: 0o600 });
  await rename(temporary, path.join(directory, "job.json"));
}

export function privatePersonalTalkingOutput(user: WebUser, id: string) {
  if (!JOB_ID.test(id)) throw new Error("任务 ID 无效");
  return path.join(personalLibraryOwnerDir(user), "talking", `${id}.mp4`);
}

export async function getPersonalTalkingJob(user: WebUser, kind: PersonalTalkingKind, avatarId: string, actionId: string): Promise<PersonalTalkingJob | null> {
  const active = store.jobs.get(key(user, kind, avatarId, actionId));
  if (active) return active;
  const entries = await readdir(root(user)).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return [];
    throw error;
  });
  const matches = (await Promise.all(entries.filter((entry) => JOB_ID.test(entry) && entry.startsWith(`${kind}-`)).map(async (entry) => {
    try {
      const job = JSON.parse(await readFile(path.join(jobDir(user, entry), "job.json"), "utf8")) as PersonalTalkingJob;
      return job.id === entry && job.kind === kind && job.avatarId === avatarId && job.actionId === actionId
        && ["queued", "processing", "ready_for_review", "success", "failed"].includes(job.state) ? job : null;
    } catch { return null; }
  }))).filter((job): job is PersonalTalkingJob => job !== null).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const job = matches[0];
  if (!job) return null;
  if (job.state === "queued" || job.state === "processing") {
    job.state = "failed";
    job.retryBlocked = true;
    job.error = "服务在生成期间重启，请先核对远端任务状态，避免重复提交。";
    job.updatedAt = new Date().toISOString();
    await persist(user, job);
  }
  store.jobs.set(key(user, kind, avatarId, actionId), job);
  return job;
}

export async function startPersonalTalkingJob(input: {
  user: WebUser; kind: PersonalTalkingKind; avatarId: string; actionId: string;
  audio?: Buffer; rightsConfirmed?: boolean; usageScope?: string;
}): Promise<PersonalTalkingJob> {
  const { user, kind, avatarId, actionId } = input;
  if (input.audio && (!input.audio.length || input.audio.length > MAX_AUDIO_BYTES)) throw new Error("参考音频需小于 20MB");
  if (kind === "wav2lip" && (!input.audio || !input.rightsConfirmed || !["personal", "research", "internal_evaluation"].includes(input.usageScope ?? ""))) {
    throw new Error("Wav2Lip 需要参考音频、素材使用权确认及非商业用途");
  }
  const jobKey = key(user, kind, avatarId, actionId);
  const pending = store.pending.get(jobKey);
  if (pending) return pending;
  const creation = createJob(input);
  store.pending.set(jobKey, creation);
  try { return await creation; }
  finally { if (store.pending.get(jobKey) === creation) store.pending.delete(jobKey); }
}

export async function resumePersonalTalkingJob(user: WebUser, kind: PersonalTalkingKind, avatarId: string, actionId: string): Promise<PersonalTalkingJob | null> {
  const job = await getPersonalTalkingJob(user, kind, avatarId, actionId);
  if (!job || job.state !== "failed" || !job.retryBlocked) return job;
  const avatar = await findPersonalAvatar(user, avatarId);
  const action = avatar?.actions.find((item) => item.avatar_action_id === actionId && !item.deleted_at && item.video_url === job.sourceUrl);
  if (!avatar || avatar.deletedAt || !action) throw new Error("原动作底片已变更，不能恢复旧任务");
  const connection = await loadUserTalkingService(user, kind);
  if (!connection || !(await probeModelService(kind, connection)).ready) throw new Error("个人模型服务尚未配置或未就绪");
  const directory = jobDir(user, job.id);
  const hasReference = await stat(path.join(directory, "reference.wav")).catch(() => null);
  const hasInput = await stat(path.join(directory, "reference.input")).catch(() => null);
  if (kind === "wav2lip" && !hasReference && !hasInput) throw new Error("参考音频已丢失，不能恢复旧任务");
  job.state = "queued";
  job.retryBlocked = false;
  job.error = undefined;
  job.updatedAt = new Date().toISOString();
  await persist(user, job);
  store.tail = store.tail.catch(() => undefined).then(() => execute(user, job, action.display_name, connection));
  return job;
}

async function createJob(input: {
  user: WebUser; kind: PersonalTalkingKind; avatarId: string; actionId: string;
  audio?: Buffer; rightsConfirmed?: boolean; usageScope?: string;
}): Promise<PersonalTalkingJob> {
  const { user, kind, avatarId, actionId } = input;
  const avatar = await findPersonalAvatar(user, avatarId);
  const action = avatar?.actions.find((item) => item.avatar_action_id === actionId && !item.deleted_at && item.video_url);
  if (!avatar || avatar.deletedAt || !action?.video_url) throw new Error("找不到可用的个人动作底片");
  const existing = action.talking_variants?.find((variant) => variant.method === kind && !variant.deleted_at && variant.source_video_url === action.video_url);
  if (existing) return { id: existing.id, kind, state: "success", avatarId, actionId, sourceUrl: action.video_url, createdAt: avatar.createdAt, updatedAt: avatar.updatedAt, variant: existing };
  const current = await getPersonalTalkingJob(user, kind, avatarId, actionId);
  if (current && current.sourceUrl === action.video_url && (["queued", "processing", "ready_for_review"].includes(current.state) || current.retryBlocked)) return current;
  const connection = await loadUserTalkingService(user, kind);
  if (!connection || !(await probeModelService(kind, connection)).ready) throw new Error(`${kind === "musetalk" ? "MuseTalk" : "Wav2Lip"} 个人服务尚未配置或未就绪`);
  const motionId = /^\/api\/user\/motion-assets\/([a-f0-9]{64})\?preview=1$/.exec(action.video_url)?.[1];
  if (!motionId) throw new Error("个人动作底片地址无效");
  const video = await readPersonalMotionVideo(user, motionId);
  if (!video || video.byteLength > 50 * 1024 * 1024) throw new Error("个人动作底片不可用或超过 50MB");
  const now = new Date().toISOString();
  const job: PersonalTalkingJob = { id: `${kind}-${randomUUID()}`, kind, state: "queued", avatarId, actionId, sourceUrl: action.video_url, createdAt: now, updatedAt: now, usageScope: input.usageScope };
  const directory = jobDir(user, job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(path.join(directory, "source.mp4"), video, { flag: "wx", mode: 0o600 });
  if (input.audio) await writeFile(path.join(directory, "reference.input"), input.audio, { flag: "wx", mode: 0o600 });
  store.jobs.set(key(user, kind, avatarId, actionId), job);
  await persist(user, job);
  store.tail = store.tail.catch(() => undefined).then(() => execute(user, job, action.display_name, connection));
  return job;
}

async function execute(user: WebUser, job: PersonalTalkingJob, actionName: string, connection: { url: string; token: string }) {
  const directory = jobDir(user, job.id);
  const published = privatePersonalTalkingOutput(user, job.id);
  try {
    job.state = "processing";
    job.updatedAt = new Date().toISOString();
    await persist(user, job);
    const input = path.join(directory, "reference.input");
    const reference = path.join(directory, "reference.wav");
    if (await stat(reference).catch(() => null)) {
      // Recovery reuses the original audio and X-Job-Id to avoid a second GPU submission.
    } else if (await stat(input).catch(() => null)) {
      await run("ffmpeg", ["-v", "error", "-y", "-i", input, "-vn", "-ac", "1", "-ar", "16000", reference], { timeout: 60_000 });
    } else {
      const builtIn = process.env.MUSETALK_REFERENCE_AUDIO || path.join(process.cwd(), "research-assets/avatar-evaluation/2026-09-08/soft-response/reference.wav");
      await writeFile(reference, await readFile(builtIn), { flag: "wx", mode: 0o600 });
    }
    if (job.kind === "wav2lip") {
      const probe = await run("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", reference], { timeout: 10_000 });
      const seconds = Number(probe.stdout.trim());
      if (!Number.isFinite(seconds) || seconds < 0.3 || seconds > 30) throw new Error("参考音频时长需在 0.3 至 30 秒之间");
    }
    const output = await runInferenceServiceJob({
      baseUrl: connection.url, token: connection.token, jobId: job.id,
      sourceVideo: await readFile(path.join(directory, "source.mp4")), referenceAudio: await readFile(reference),
      rightsConfirmed: true, usageScope: job.kind === "wav2lip" ? job.usageScope : undefined,
      timeoutMs: job.kind === "wav2lip" ? 960_000 : 1_830_000,
    });
    await writeFile(path.join(directory, "output.mp4"), output, { mode: 0o600 });
    await run("ffmpeg", ["-v", "error", "-i", path.join(directory, "output.mp4"), "-f", "null", "-"], { timeout: 60_000 });
    const avatar = await findPersonalAvatar(user, job.avatarId);
    const action = avatar?.actions.find((item) => item.avatar_action_id === job.actionId && !item.deleted_at);
    if (!avatar || avatar.deletedAt || !action || action.video_url !== job.sourceUrl) throw new Error("动作底片已改变");
    await mkdir(path.dirname(published), { recursive: true, mode: 0o700 });
    await rename(path.join(directory, "output.mp4"), published);
    job.variant = {
      id: job.id, display_name: `${actionName.slice(0, 80)} · ${job.kind === "musetalk" ? "MuseTalk 1.5" : "Wav2Lip"}`,
      method: job.kind, source_video_url: job.sourceUrl,
      video_url: `/api/user/avatars/${job.avatarId}/actions/${job.actionId}/talking-variants/${job.id}/video`,
      processing: job.kind === "wav2lip" ? "mouth-only" : "original", validation: "pending",
    };
    job.state = "ready_for_review";
    job.updatedAt = new Date().toISOString();
    await persist(user, job);
    await rm(path.join(directory, "reference.input"), { force: true }).catch(() => undefined);
  } catch (error) {
    await rm(published, { force: true }).catch(() => undefined);
    job.state = "failed";
    job.retryBlocked = true;
    job.error = `${job.kind === "musetalk" ? "MuseTalk" : "Wav2Lip"} 生成失败。请核对服务任务后重试。`;
    job.updatedAt = new Date().toISOString();
    await persist(user, job).catch(() => undefined);
    console.error(`Personal talking job ${job.id} failed`, error instanceof Error ? error.name : "unknown error");
  }
}

export async function acceptPersonalTalkingJob(user: WebUser, kind: PersonalTalkingKind, avatarId: string, actionId: string, jobId: string) {
  const job = await getPersonalTalkingJob(user, kind, avatarId, actionId);
  if (!job || job.id !== jobId || job.state !== "ready_for_review" || !job.variant) throw new Error("找不到待确认的口型对齐");
  if (!(await stat(privatePersonalTalkingOutput(user, jobId))).isFile()) throw new Error("讲话视频不可用");
  const action = await attachPersonalTalkingVariant(user, avatarId, actionId, job.variant);
  job.state = "success";
  job.updatedAt = new Date().toISOString();
  await persist(user, job);
  return { job, action };
}
