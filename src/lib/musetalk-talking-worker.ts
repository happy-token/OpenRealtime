import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, readdir, realpath, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { attachTalkingVariant, findOwnedAvatar } from "./avatar-catalog-repository";
import { avatarAssetControlRequest } from "./avatar-assets-server";
import type { AvatarTalkingVariant } from "./avatar-records";

const exec = promisify(execFile);
const LIMIT = 50 * 1024 * 1024;
export type TalkingJob = {
  id: string;
  state: "queued" | "processing" | "success" | "failed";
  avatarId?: string;
  actionId?: string;
  sourceUrl?: string;
  createdAt?: string;
  updatedAt?: string;
  retryBlocked?: boolean;
  error?: string;
  variant?: AvatarTalkingVariant;
};
type Store = { jobs: Map<string, TalkingJob>; tail: Promise<void> };
const globalStore = globalThis as typeof globalThis & { __musetalkTalkingJobs?: Store };
const store = globalStore.__musetalkTalkingJobs ??= { jobs: new Map(), tail: Promise.resolve() };
const keyFor = (avatarId: string, actionId: string) => `${avatarId}/${actionId}`;
const quote = (value: string) => `'${value.replace(/'/g, "'\\''")}'`;

export async function getTalkingJob(avatarId: string, actionId: string) {
  const key = keyFor(avatarId, actionId);
  const active = store.jobs.get(key);
  if (active) return active;
  const recovered = await findPersistedJob(avatarId, actionId);
  if (!recovered) return null;
  if (recovered.state === "queued" || recovered.state === "processing") {
    recovered.state = "failed";
    recovered.retryBlocked = true;
    recovered.error = "服务曾在生成期间重启，远端任务状态无法确认。为避免重复消耗 GPU，请先核对任务目录和远端输出。";
    recovered.updatedAt = new Date().toISOString();
    await persistJob(recovered);
  }
  store.jobs.set(key, recovered);
  return recovered;
}

/** Only owned artifact endpoints or files confined to public may be used as source media. */
export async function readTalkingSource(source: string): Promise<Buffer> {
  const artifact = /^\/api\/avatar-assets\/artifacts\/([A-Za-z0-9-]+)$/.exec(source);
  if (artifact) {
    const response = await avatarAssetControlRequest(`/avatar-assets/artifacts/${artifact[1]}`);
    if (!response.ok || !response.body) throw new Error("动作底片读取失败");
    const chunks: Uint8Array[] = [];
    let length = 0;
    const reader = response.body.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > LIMIT) throw new Error("动作底片不能超过 50MB");
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    return Buffer.concat(chunks);
  }
  if (!source.startsWith("/digital-human/") || source.includes("\\") || source.includes("?")) throw new Error("不支持的动作底片地址");
  const root = await realpath(path.join(process.cwd(), "public", "digital-human"));
  const file = await realpath(path.join(process.cwd(), "public", source));
  if (!file.startsWith(root + path.sep) || (await stat(file)).size > LIMIT) throw new Error("动作底片路径或大小无效");
  return readFile(file);
}

export async function startTalkingJob(avatarId: string, actionId: string): Promise<TalkingJob> {
  const avatar = await findOwnedAvatar(avatarId);
  const action = avatar?.actions.find(item => item.avatar_action_id === actionId && !item.deleted_at);
  if (!avatar || avatar.deleted_at || !action?.video_url) throw new Error("找不到可用动作底片");
  const key = keyFor(avatarId, actionId);
  const source = action.video_url;
  const current = await getTalkingJob(avatarId, actionId);
  const matchesCurrentSource = !current?.sourceUrl || current.sourceUrl === source;
  if (current && matchesCurrentSource && (current.state === "queued" || current.state === "processing" || current.retryBlocked)) return current;
  const existing = action.talking_variants?.find(v => v.method === "musetalk" && v.source_video_url === action.video_url);
  if (existing) return { id: existing.id, state: "success", variant: existing };
  const host = process.env.MUSETALK_SSH_HOST?.trim() || "dev";
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._@-]*$/.test(host)) throw new Error("GPU SSH 配置无效");
  const now = new Date().toISOString();
  const job: TalkingJob = {
    id: `musetalk-${randomUUID()}`,
    state: "queued",
    avatarId,
    actionId,
    sourceUrl: source,
    createdAt: now,
    updatedAt: now,
  };
  store.jobs.set(key, job);
  await persistJob(job);
  store.tail = store.tail.then(async () => {
    job.state = "processing";
    job.updatedAt = new Date().toISOString();
    await persistJob(job);
    const local = path.join(talkingJobRoot(), job.id);
    let publishedPath: string | undefined;
    try {
      await mkdir(local, { recursive: true });
      await writeFile(path.join(local, "source.mp4"), await readTalkingSource(source));
      const reference = process.env.MUSETALK_REFERENCE_AUDIO || path.join(process.cwd(), "research-assets/avatar-evaluation/2026-09-08/soft-response/reference.wav");
      const remote = `/root/lipsync-eval/openrealtime-talking/${job.id}`;
      const runtime = process.env.MUSETALK_REMOTE_ROOT || "/root/lipsync-eval/musetalk";
      const python = process.env.MUSETALK_REMOTE_PYTHON || "/root/lipsync-eval/venv-musetalk/bin/python";
      const sshArgs = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host];
      const run = async (command: string, args: string[], timeout = 60_000) => exec(command, args, { timeout, maxBuffer: 8 * 1024 * 1024 });
      await run("ssh", [...sshArgs, `mkdir -p ${quote(remote)}`]);
      await run("scp", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", path.join(local, "source.mp4"), `${host}:${remote}/source.mp4`]);
      await run("scp", ["-o", "BatchMode=yes", reference, `${host}:${remote}/reference.wav`]);
      await run("scp", ["-o", "BatchMode=yes", path.join(process.cwd(), "scripts/generate_musetalk_talking.sh"), `${host}:${remote}/run.sh`]);
      const result = await run("ssh", [...sshArgs, `timeout 1800 bash ${quote(remote + "/run.sh")} ${quote(remote)} ${quote(runtime)} ${quote(python)}`], 1_830_000);
      await writeFile(path.join(local, "inference.log"), result.stdout + result.stderr);
      await run("scp", ["-o", "BatchMode=yes", `${host}:${remote}/output.mp4`, path.join(local, "output.mp4")]);
      await run("ffmpeg", ["-v", "error", "-i", path.join(local, "output.mp4"), "-f", "null", "-"]);
      const output = path.join(process.cwd(), "public", "digital-human", "talking-variants");
      await mkdir(output, { recursive: true });
      publishedPath = path.join(output, `${job.id}.mp4`);
      await rename(path.join(local, "output.mp4"), publishedPath);
      const variant: AvatarTalkingVariant = { id: job.id, display_name: `${action.display_name.slice(0, 80)} · MuseTalk 1.5`, method: "musetalk", source_video_url: source, video_url: `/digital-human/talking-variants/${job.id}.mp4`, processing: "original", validation: "pending" };
      // Re-check source identity and deletion under the catalog lock before publishing.
      await attachTalkingVariant(avatarId, actionId, variant);
      job.variant = variant;
      job.state = "success";
      job.updatedAt = new Date().toISOString();
      await persistJob(job);
    } catch (error) {
      if (publishedPath) await unlink(publishedPath).catch(cleanupError => console.error("Cannot remove unpublished talking video", cleanupError));
      job.state = "failed";
      job.retryBlocked = true;
      job.updatedAt = new Date().toISOString();
      job.error = "MuseTalk 讲话素材生成失败。为避免远端任务仍在运行时重复消耗 GPU，请先检查任务日志和远端输出。";
      await persistJob(job).catch(persistError => console.error("Cannot persist failed talking job", persistError));
      console.error(`Talking job ${job.id} failed`, error);
      await writeFile(path.join(local, "error.log"), String(error)).catch(logError => console.error("Cannot save talking job error", logError));
    }
  });
  return job;
}


function talkingJobRoot() {
  return process.env.MUSETALK_JOB_ROOT ?? path.join(process.cwd(), ".openrealtime", "talking-jobs");
}

async function persistJob(job: TalkingJob) {
  const directory = path.join(talkingJobRoot(), job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const target = path.join(directory, "job.json");
  const temporary = path.join(directory, `job.${process.pid}.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job, null, 2), { mode: 0o600 });
  await rename(temporary, target);
}

async function findPersistedJob(avatarId: string, actionId: string) {
  let entries: string[];
  try {
    entries = await readdir(talkingJobRoot());
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return null;
    throw error;
  }
  const jobs = await Promise.all(entries
    .filter((entry) => /^musetalk-[0-9a-f-]{36}$/.test(entry))
    .map(async (entry) => {
      try {
        const parsed: unknown = JSON.parse(await readFile(path.join(talkingJobRoot(), entry, "job.json"), "utf8"));
        return isTalkingJob(parsed) ? parsed : null;
      } catch {
        return null;
      }
    }));
  return jobs
    .filter((job): job is TalkingJob => Boolean(job && job.avatarId === avatarId && job.actionId === actionId))
    .sort((left, right) => Date.parse(right.updatedAt ?? right.createdAt ?? "") - Date.parse(left.updatedAt ?? left.createdAt ?? ""))[0] ?? null;
}

function isTalkingJob(value: unknown): value is TalkingJob {
  if (!value || typeof value !== "object") return false;
  const job = value as Partial<TalkingJob>;
  return typeof job.id === "string"
    && ["queued", "processing", "success", "failed"].includes(job.state ?? "")
    && typeof job.avatarId === "string"
    && typeof job.actionId === "string";
}
