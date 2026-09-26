import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, readdir, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { attachTalkingVariant, findOwnedAvatar } from "./avatar-catalog-repository";
import type { AvatarTalkingVariant } from "./avatar-records";
import { readTalkingSource } from "./musetalk-talking-worker";
import { attachPersonalTalkingVariant, findPersonalAvatar } from "./personal-avatar-library";
import { personalLibraryOwnerDir, readPersonalMotionVideo } from "./personal-motion-library";
import type { WebUser } from "./user-session";
import { runLipForcingServiceJob } from "./lipforcing-service-client";
import { modelServiceConnection } from "./model-service-connections";
import { loadUserLipsyncService, probeUserLipsyncService } from "./user-lipsync-service";

const exec = promisify(execFile);
const JOB_ID = /^lipforcing-[0-9a-f-]{36}$/;
const MAX_REFERENCE_BYTES = 20 * 1024 * 1024;

export type LipForcingJob = {
  id: string;
  state: "queued" | "processing" | "ready_for_review" | "success" | "failed";
  avatarId: string;
  actionId: string;
  sourceUrl: string;
  createdAt: string;
  updatedAt: string;
  retryBlocked?: boolean;
  error?: string;
  variant?: AvatarTalkingVariant;
};

type Store = { jobs: Map<string, LipForcingJob>; tail: Promise<void> };
const globalStore = globalThis as typeof globalThis & { __lipForcingTalkingJobs?: Store };
const store = globalStore.__lipForcingTalkingJobs ??= { jobs: new Map(), tail: Promise.resolve() };
const keyFor = (avatarId: string, actionId: string) => `${avatarId}/${actionId}`;
const quote = (value: string) => `'${value.replace(/'/g, "'\\''")}'`;
const jobRoot = () => process.env.LIPFORCING_JOB_ROOT ?? path.join(process.cwd(), ".openrealtime", "lipforcing-jobs");

export async function getLipForcingJob(avatarId: string, actionId: string): Promise<LipForcingJob | null> {
  const key = keyFor(avatarId, actionId);
  const active = store.jobs.get(key);
  if (active) return active;
  const persisted = await findPersistedJob(avatarId, actionId);
  if (!persisted) return null;
  if (persisted.state === "queued" || persisted.state === "processing") {
    persisted.state = "failed";
    persisted.retryBlocked = true;
    persisted.error = "服务曾在生成期间重启。请先核对远端任务和输出，避免重复消耗 GPU。";
    persisted.updatedAt = new Date().toISOString();
    await persistJob(persisted);
  }
  store.jobs.set(key, persisted);
  return persisted;
}

export function privateLipForcingOutput(user: WebUser, jobId: string) {
  if (!JOB_ID.test(jobId)) throw new Error("任务 ID 无效");
  return path.join(personalLibraryOwnerDir(user), "talking", `${jobId}.mp4`);
}

export async function startLipForcingJob(avatarId: string, actionId: string, referenceAudio: Buffer, user?: WebUser): Promise<LipForcingJob> {
  if (!referenceAudio.length || referenceAudio.length > MAX_REFERENCE_BYTES) throw new Error("参考音频大小无效");
  const avatar = user ? await findPersonalAvatar(user, avatarId) : await findOwnedAvatar(avatarId);
  const action = avatar?.actions.find((item) => item.avatar_action_id === actionId && !item.deleted_at && item.video_url);
  if (!avatar || ("deletedAt" in avatar ? avatar.deletedAt : avatar.deleted_at) || !action?.video_url) throw new Error("找不到可用动作底片");
  const current = await getLipForcingJob(avatarId, actionId);
  if (current && current.sourceUrl === action.video_url
    && (current.state === "queued" || current.state === "processing" || current.state === "ready_for_review" || current.retryBlocked)) return current;
  const existing = action.talking_variants?.find((item) => item.method === "lipforcing" && !item.deleted_at && item.video_url && item.source_video_url === action.video_url);
  if (existing) return { id: existing.id, state: "success", avatarId, actionId, sourceUrl: action.video_url, createdAt: "createdAt" in avatar ? avatar.createdAt : avatar.created_at, updatedAt: "updatedAt" in avatar ? avatar.updatedAt : avatar.updated_at, variant: existing };
  const connection = user ? await loadUserLipsyncService(user) : await modelServiceConnection("lipforcing");
  if (user && (!connection || !await probeUserLipsyncService(connection))) throw new Error("个人口型服务尚未配置或未就绪，请在设置中检查连接");
  const apiUrl = user ? connection?.url : connection?.url || process.env.LIPFORCING_API_URL?.trim();
  const host = (process.env.LIPFORCING_SSH_HOST || process.env.MUSETALK_SSH_HOST)?.trim();
  if (!apiUrl && (!host || !/^[a-zA-Z0-9][a-zA-Z0-9._@-]*$/.test(host))) throw new Error("Lip Forcing GPU 服务尚未配置");
  const now = new Date().toISOString();
  const job: LipForcingJob = { id: `lipforcing-${randomUUID()}`, state: "queued", avatarId, actionId, sourceUrl: action.video_url, createdAt: now, updatedAt: now };
  store.jobs.set(keyFor(avatarId, actionId), job);
  await persistJob(job);
  store.tail = store.tail.catch(() => undefined).then(async () => {
    job.state = "processing";
    job.updatedAt = new Date().toISOString();
    await persistJob(job);
    const local = path.join(jobRoot(), job.id);
    try {
      await mkdir(local, { recursive: true, mode: 0o700 });
      if (user) {
        const motionId = /^\/api\/user\/motion-assets\/([a-f0-9]{64})\?preview=1$/.exec(action.video_url!)?.[1];
        if (!motionId) throw new Error("个人动作底片地址无效");
        const video = await readPersonalMotionVideo(user, motionId);
        if (!video || video.byteLength > 50 * 1024 * 1024) throw new Error("个人动作底片不可用或超过 50MB");
        await writeFile(path.join(local, "source.mp4"), video);
      } else {
        await writeFile(path.join(local, "source.mp4"), await readTalkingSource(action.video_url!));
      }
      await writeFile(path.join(local, "reference.wav"), referenceAudio);
      if (apiUrl) {
        const output = await runLipForcingServiceJob({
          baseUrl: apiUrl,
          token: user ? connection?.token : connection?.url ? connection.token : process.env.LIPFORCING_API_TOKEN?.trim(),
          jobId: job.id,
          sourceVideo: await readFile(path.join(local, "source.mp4")),
          referenceAudio: await readFile(path.join(local, "reference.wav")),
        });
        await writeFile(path.join(local, "output.mp4"), output, { mode: 0o600 });
      } else {
        const remote = `/root/lipsync-eval/openrealtime-lipforcing/${job.id}`;
        const runtime = process.env.LIPFORCING_REMOTE_ROOT || "/root/lipsync-eval/lipforcing-eval";
        const python = process.env.LIPFORCING_REMOTE_PYTHON || "/root/lipsync-eval/venv-lipforcing/bin/python";
        const sshArgs = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host!];
        const run = (command: string, args: string[], timeout = 60_000) => exec(command, args, { timeout, maxBuffer: 8 * 1024 * 1024 });
        await run("ssh", [...sshArgs, `mkdir -p ${quote(remote)}`]);
        await run("scp", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", path.join(local, "source.mp4"), `${host}:${remote}/source.mp4`]);
        await run("scp", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", path.join(local, "reference.wav"), `${host}:${remote}/reference.wav`]);
        await run("scp", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", path.join(process.cwd(), "scripts/generate_lipforcing_talking.sh"), `${host}:${remote}/run.sh`]);
        const result = await run("ssh", [...sshArgs, `timeout 3600 bash ${quote(remote + "/run.sh")} ${quote(remote)} ${quote(runtime)} ${quote(python)}`], 3_630_000);
        await writeFile(path.join(local, "inference.log"), result.stdout + result.stderr);
        await run("scp", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", `${host}:${remote}/output.mp4`, path.join(local, "output.mp4")]);
      }
      await publishLipForcingOutput(job, local, action.display_name, user);
    } catch (error) {
      job.state = "failed";
      job.retryBlocked = true;
      job.error = "Lip Forcing 生成失败。请核对 GPU 主机的任务日志与输出后重试。";
      job.updatedAt = new Date().toISOString();
      await persistJob(job).catch(() => undefined);
      await writeFile(path.join(local, "error.log"), String(error)).catch(() => undefined);
      console.error(`Lip Forcing job ${job.id} failed`, error);
    }
  });
  return job;
}

export async function resumeLipForcingJob(avatarId: string, actionId: string, user?: WebUser): Promise<LipForcingJob | null> {
  const job = await getLipForcingJob(avatarId, actionId);
  if (!job || job.state !== "failed" || !job.retryBlocked) return job;
  const avatar = user ? await findPersonalAvatar(user, avatarId) : await findOwnedAvatar(avatarId);
  const action = avatar?.actions.find((item) => item.avatar_action_id === actionId && !item.deleted_at && item.video_url === job.sourceUrl);
  if (!action?.video_url) throw new Error("原动作底片已变更，不能恢复旧任务");
  const connection = user ? await loadUserLipsyncService(user) : await modelServiceConnection("lipforcing");
  if (!connection?.url || (user && !await probeUserLipsyncService(connection))) throw new Error("口型服务尚未配置或未就绪，不能恢复旧任务");
  const local = path.join(jobRoot(), job.id);
  const sourceVideo = await readFile(path.join(local, "source.mp4"));
  const referenceAudio = await readFile(path.join(local, "reference.wav"));
  job.state = "processing";
  job.retryBlocked = false;
  job.error = undefined;
  job.updatedAt = new Date().toISOString();
  await persistJob(job);
  store.tail = store.tail.catch(() => undefined).then(async () => {
    try {
      // The GPU service treats X-Job-Id as idempotent: a completed job returns its existing result.
      const output = await runLipForcingServiceJob({
        baseUrl: connection.url,
        token: connection.token,
        jobId: job.id,
        sourceVideo,
        referenceAudio,
      });
      await writeFile(path.join(local, "output.mp4"), output, { mode: 0o600 });
      await publishLipForcingOutput(job, local, action.display_name, user);
    } catch (error) {
      job.state = "failed";
      job.retryBlocked = true;
      job.error = "Lip Forcing 任务恢复失败，请检查 GPU 服务连接与任务输出。";
      job.updatedAt = new Date().toISOString();
      await persistJob(job).catch(() => undefined);
      await writeFile(path.join(local, "error.log"), String(error)).catch(() => undefined);
      console.error(`Lip Forcing job ${job.id} recovery failed`, error);
    }
  });
  return job;
}

async function publishLipForcingOutput(job: LipForcingJob, local: string, actionName: string, user?: WebUser) {
  await exec("ffmpeg", ["-v", "error", "-i", path.join(local, "output.mp4"), "-f", "null", "-"], { timeout: 60_000, maxBuffer: 8 * 1024 * 1024 });
  const directory = user ? path.dirname(privateLipForcingOutput(user, job.id)) : path.join(process.cwd(), "public", "digital-human", "talking-variants");
  await mkdir(directory, { recursive: true });
  const publishedPath = user ? privateLipForcingOutput(user, job.id) : path.join(directory, `${job.id}.mp4`);
  await rename(path.join(local, "output.mp4"), publishedPath);
  try {
    job.variant = {
      id: job.id,
      display_name: `${actionName.slice(0, 80)} · Lip Forcing`,
      method: "lipforcing",
      source_video_url: job.sourceUrl,
      video_url: user ? `/api/user/avatars/${job.avatarId}/actions/${job.actionId}/talking-variants/${job.id}/video` : `/digital-human/talking-variants/${job.id}.mp4`,
      processing: "original",
      validation: "pending",
    };
    job.state = "ready_for_review";
    job.retryBlocked = false;
    job.error = undefined;
    job.updatedAt = new Date().toISOString();
    await persistJob(job);
  } catch (error) {
    await unlink(publishedPath).catch(() => undefined);
    throw error;
  }
}

export async function acceptLipForcingJob(avatarId: string, actionId: string, jobId: string, user?: WebUser) {
  const job = await getLipForcingJob(avatarId, actionId);
  if (!job || job.id !== jobId || job.state !== "ready_for_review" || !job.variant || !JOB_ID.test(job.id)) throw new Error("找不到待确认的口型对齐");
  const file = user ? privateLipForcingOutput(user, job.id) : path.join(process.cwd(), "public", "digital-human", "talking-variants", `${job.id}.mp4`);
  if (!(await stat(file)).isFile()) throw new Error("讲话视频不可用");
  const action = user ? await attachPersonalTalkingVariant(user, avatarId, actionId, job.variant) : await attachTalkingVariant(avatarId, actionId, job.variant);
  job.state = "success";
  job.updatedAt = new Date().toISOString();
  await persistJob(job);
  return { job, action };
}

async function persistJob(job: LipForcingJob) {
  const directory = path.join(jobRoot(), job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const target = path.join(directory, "job.json");
  const temporary = path.join(directory, `job.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, target);
}

async function findPersistedJob(avatarId: string, actionId: string): Promise<LipForcingJob | null> {
  let entries: string[];
  try { entries = await readdir(jobRoot()); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
  const jobs = await Promise.all(entries.filter((entry) => JOB_ID.test(entry)).map(async (entry) => {
    try {
      const value: unknown = JSON.parse(await readFile(path.join(jobRoot(), entry, "job.json"), "utf8"));
      if (!value || typeof value !== "object") return null;
      const job = value as LipForcingJob;
      return job.id === entry && job.avatarId === avatarId && job.actionId === actionId
        && ["queued", "processing", "ready_for_review", "success", "failed"].includes(job.state) ? job : null;
    } catch { return null; }
  }));
  return jobs.filter((job): job is LipForcingJob => Boolean(job))
    .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))[0] ?? null;
}
