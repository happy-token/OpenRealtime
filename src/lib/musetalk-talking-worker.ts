import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, realpath, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { attachTalkingVariant, findOwnedAvatar } from "./avatar-catalog-repository";
import { avatarAssetControlRequest } from "./avatar-assets-server";
import type { AvatarTalkingVariant } from "./avatar-records";

const exec = promisify(execFile);
const LIMIT = 50 * 1024 * 1024;
export type TalkingJob = { id: string; state: "queued" | "processing" | "success" | "failed"; error?: string; variant?: AvatarTalkingVariant };
type Store = { jobs: Map<string, TalkingJob>; tail: Promise<void> };
const globalStore = globalThis as typeof globalThis & { __musetalkTalkingJobs?: Store };
const store = globalStore.__musetalkTalkingJobs ??= { jobs: new Map(), tail: Promise.resolve() };
const keyFor = (avatarId: string, actionId: string) => `${avatarId}/${actionId}`;
const quote = (value: string) => `'${value.replace(/'/g, "'\\''")}'`;

export function getTalkingJob(avatarId: string, actionId: string) {
  return store.jobs.get(keyFor(avatarId, actionId)) ?? null;
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
  const current = store.jobs.get(key);
  if (current && (current.state === "queued" || current.state === "processing")) return current;
  const existing = action.talking_variants?.find(v => v.method === "musetalk" && v.source_video_url === action.video_url);
  if (existing) return { id: existing.id, state: "success", variant: existing };
  const host = process.env.MUSETALK_SSH_HOST?.trim() || "dev";
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._@-]*$/.test(host)) throw new Error("GPU SSH 配置无效");
  const job: TalkingJob = { id: `musetalk-${randomUUID()}`, state: "queued" };
  store.jobs.set(key, job);
  const source = action.video_url;
  store.tail = store.tail.then(async () => {
    job.state = "processing";
    const local = path.join(process.cwd(), ".openrealtime", "talking-jobs", job.id);
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
    } catch (error) {
      if (publishedPath) await unlink(publishedPath).catch(cleanupError => console.error("Cannot remove unpublished talking video", cleanupError));
      job.state = "failed";
      job.error = "MuseTalk 讲话素材生成失败，请检查 GPU 连接和任务日志后重试。";
      console.error(`Talking job ${job.id} failed`, error);
      await writeFile(path.join(local, "error.log"), String(error)).catch(logError => console.error("Cannot save talking job error", logError));
    }
  });
  return job;
}
