import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { attachTalkingVariant, findOwnedAvatar } from "./avatar-catalog-repository";
import { readTalkingSource } from "./musetalk-talking-worker";
import type { AvatarTalkingVariant } from "./avatar-records";
import { modelServiceConnection } from "./model-service-connections";
import { runLipForcingServiceJob } from "./lipforcing-service-client";

const run = promisify(execFile);
const MAX_AUDIO_BYTES = 20 * 1024 * 1024;
const MAX_REQUEST_BYTES = MAX_AUDIO_BYTES + 1024 * 1024;
const ID = /^wav2lip-[0-9a-f-]{36}$/;
const store = globalThis as typeof globalThis & { __wav2lipTalkingJobs?: { jobs: Map<string, Wav2LipJob>; pendingStarts: Map<string, Promise<Wav2LipJob>>; tail: Promise<void> } };
const jobs = store.__wav2lipTalkingJobs ??= { jobs: new Map(), pendingStarts: new Map(), tail: Promise.resolve() };
jobs.pendingStarts ??= new Map();

export type Wav2LipJob = {
  id: string;
  state: "queued" | "processing" | "ready_for_review" | "success" | "failed";
  previewOnly?: boolean;
  avatarId: string;
  actionId: string;
  sourceUrl: string;
  createdAt: string;
  updatedAt: string;
  error?: string;
  usageScope?: string;
  variant?: AvatarTalkingVariant;
};

function root() { return process.env.WAV2LIP_JOB_ROOT || path.join(process.cwd(), ".openrealtime", "wav2lip-jobs"); }
function key(avatarId: string, actionId: string) { return `${avatarId}/${actionId}`; }
function jobDir(id: string) { return path.join(root(), id); }

async function persist(job: Wav2LipJob) {
  const directory = jobDir(job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = path.join(directory, `job.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, path.join(directory, "job.json"));
}

export async function getWav2LipJob(avatarId: string, actionId: string): Promise<Wav2LipJob | null> {
  const active = jobs.jobs.get(key(avatarId, actionId));
  if (active) return active;
  let entries: string[];
  try { entries = await readdir(root()); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  const recovered = (await Promise.all(entries.filter(entry => ID.test(entry)).map(async entry => {
    try {
      const value = JSON.parse(await readFile(path.join(jobDir(entry), "job.json"), "utf8")) as Wav2LipJob;
      return value.id === entry && value.avatarId === avatarId && value.actionId === actionId && ["queued", "processing", "ready_for_review", "success", "failed"].includes(value.state) ? value : null;
    } catch { return null; }
  }))).filter((value): value is Wav2LipJob => value !== null).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
  if (!recovered) return null;
  if (recovered.state === "queued" || recovered.state === "processing") {
    recovered.state = "failed";
    recovered.error = "生成服务中断，请重新提交参考音频。";
    recovered.updatedAt = new Date().toISOString();
    await persist(recovered);
  }
  jobs.jobs.set(key(avatarId, actionId), recovered);
  return recovered;
}

export async function startWav2LipJob(input: {
  avatarId: string; actionId: string; audio: File; rightsConfirmed: boolean; usageScope: string; previewOnly?: boolean;
}): Promise<Wav2LipJob> {
  if (!input.rightsConfirmed) throw new Error("请确认拥有底片、人物与音频的使用权");
  if (!["personal", "research", "internal_evaluation"].includes(input.usageScope)) throw new Error("标准 Wav2Lip 仅支持非商业用途");
  if (!input.audio || input.audio.size < 100 || input.audio.size > MAX_AUDIO_BYTES) throw new Error("参考音频需小于 20MB");
  if (!["audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp4", "audio/x-m4a"].includes(input.audio.type)) throw new Error("请上传 WAV、MP3 或 M4A 音频");
  if (!/\.(wav|mp3|m4a)$/i.test(input.audio.name)) throw new Error("参考音频文件名需以 .wav、.mp3 或 .m4a 结尾");
  const jobKey = key(input.avatarId, input.actionId);
  const pending = jobs.pendingStarts.get(jobKey);
  if (pending) return pending;
  const creation = createWav2LipJob(input);
  jobs.pendingStarts.set(jobKey, creation);
  try { return await creation; }
  finally { if (jobs.pendingStarts.get(jobKey) === creation) jobs.pendingStarts.delete(jobKey); }
}

async function createWav2LipJob(input: {
  avatarId: string; actionId: string; audio: File; rightsConfirmed: boolean; usageScope: string; previewOnly?: boolean;
}): Promise<Wav2LipJob> {
  const avatar = await findOwnedAvatar(input.avatarId);
  const action = avatar?.actions.find(item => item.avatar_action_id === input.actionId && !item.deleted_at);
  if (!avatar || avatar.deleted_at || !action?.video_url) throw new Error("找不到可用动作底片");
  const existing = action.talking_variants?.find(item => item.method === "wav2lip" && !item.deleted_at && item.source_video_url === action.video_url);
  if (existing) return { id: existing.id, state: "success", avatarId: input.avatarId, actionId: input.actionId, sourceUrl: action.video_url, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), variant: existing };
  const current = await getWav2LipJob(input.avatarId, input.actionId);
  if (current && current.sourceUrl === action.video_url && (current.state === "queued" || current.state === "processing" || current.state === "ready_for_review")) return current;
  const now = new Date().toISOString();
  const job: Wav2LipJob = { id: `wav2lip-${randomUUID()}`, state: "queued", avatarId: input.avatarId, actionId: input.actionId, sourceUrl: action.video_url, usageScope: input.usageScope, previewOnly: input.previewOnly, createdAt: now, updatedAt: now };
  const directory = jobDir(job.id);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(path.join(directory, "reference.input"), Buffer.from(await input.audio.arrayBuffer()), { flag: "wx", mode: 0o600 });
  jobs.jobs.set(key(input.avatarId, input.actionId), job);
  await persist(job);
  jobs.tail = jobs.tail.catch(error => console.error("Wav2Lip queue failure", error)).then(() => execute(job));
  return job;
}

async function execute(job: Wav2LipJob) {
  const directory = jobDir(job.id);
  const published = path.join(process.cwd(), "public", "digital-human", "talking-variants", `${job.id}.mp4`);
  try {
    job.state = "processing";
    job.updatedAt = new Date().toISOString();
    await persist(job);
    await writeFile(path.join(directory, "source.mp4"), await readTalkingSource(job.sourceUrl), { flag: "wx" });
    const audio = path.join(directory, "reference.wav");
    await run("ffmpeg", ["-v", "error", "-y", "-i", path.join(directory, "reference.input"), "-vn", "-ac", "1", "-ar", "16000", audio], { timeout: 60_000 });
    const probe = await run("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio], { timeout: 10_000 });
    const seconds = Number(probe.stdout.trim());
    if (!Number.isFinite(seconds) || seconds < 0.3 || seconds > 30) throw new Error("参考音频时长需在 0.3 至 30 秒之间");
    const output = path.join(directory, "output.mp4");
    const connection = await modelServiceConnection("wav2lip");
    if (connection.url) {
      const result = await runLipForcingServiceJob({
        baseUrl: connection.url, token: connection.token, jobId: job.id,
        sourceVideo: await readFile(path.join(directory, "source.mp4")),
        referenceAudio: await readFile(audio), rightsConfirmed: true,
        usageScope: job.usageScope || "internal_evaluation", timeoutMs: 960_000,
      });
      await writeFile(output, result, { flag: "wx", mode: 0o600 });
    } else {
      const script = path.join(process.cwd(), "scripts", "wav2lip_provider.py");
      const runtime = process.env.WAV2LIP_RUNTIME_ROOT || path.join(process.cwd(), "models", "wav2lip");
      const result = await run("python3", [script, "render", path.join(directory, "source.mp4"), audio, output, "--runtime-root", runtime, "--rights-confirmed", "--usage-scope", job.usageScope || "internal_evaluation", "--timeout-seconds", "900"], { timeout: 960_000, maxBuffer: 8 * 1024 * 1024 });
      await writeFile(path.join(directory, "inference.log"), result.stdout + result.stderr);
    }
    await mkdir(path.dirname(published), { recursive: true });
    await rename(output, published);
    const avatar = await findOwnedAvatar(job.avatarId);
    const action = avatar?.actions.find(item => item.avatar_action_id === job.actionId && !item.deleted_at);
    if (!action || action.video_url !== job.sourceUrl) throw new Error("动作底片已改变");
    const variant: AvatarTalkingVariant = { id: job.id, display_name: `${action.display_name.slice(0, 80)} · Wav2Lip`, method: "wav2lip", source_video_url: job.sourceUrl, video_url: `/digital-human/talking-variants/${job.id}.mp4`, processing: "mouth-only", validation: "pending" };
    if (!job.previewOnly) await attachTalkingVariant(job.avatarId, job.actionId, variant);
    job.variant = variant;
    job.state = job.previewOnly ? "ready_for_review" : "success";
    job.updatedAt = new Date().toISOString();
    await persist(job);
  } catch (error) {
    await rm(published, { force: true }).catch(cleanupError => console.error("Cannot remove failed Wav2Lip output", cleanupError));
    job.state = "failed";
    job.error = error instanceof Error ? `Wav2Lip 生成失败：${error.message.slice(0, 240)}` : "Wav2Lip 生成失败";
    job.updatedAt = new Date().toISOString();
    await persist(job).catch(persistError => console.error("Cannot persist Wav2Lip failure", persistError));
    await writeFile(path.join(directory, "error.log"), String(error)).catch(logError => console.error("Cannot save Wav2Lip error", logError));
  } finally {
    await rm(path.join(directory, "reference.input"), { force: true }).catch(cleanupError => console.error("Cannot remove Wav2Lip input", cleanupError));
  }
}

export async function acceptWav2LipJob(avatarId: string, actionId: string, jobId: string) {
  const job = await getWav2LipJob(avatarId, actionId);
  if (!job || job.id !== jobId || job.state !== "ready_for_review" || !job.variant) throw new Error("找不到待确认的口型对齐");
  if (!job.variant.video_url.endsWith(`/${job.id}.mp4`) || !(await stat(path.join(process.cwd(), "public", "digital-human", "talking-variants", `${job.id}.mp4`))).isFile()) throw new Error("讲话视频不可用");
  const action = await attachTalkingVariant(avatarId, actionId, job.variant);
  job.state = "success";
  job.updatedAt = new Date().toISOString();
  await persist(job);
  return { job, action };
}

export { MAX_REQUEST_BYTES };
