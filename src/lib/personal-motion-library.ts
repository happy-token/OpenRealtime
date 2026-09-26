import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import type { WebUser } from "./user-session";

export type PersonalMotionAsset = {
  id: string;
  taskId: string;
  prompt: string;
  createdAt: string;
  duration: number;
};

function libraryRoot() {
  const configured = process.env.OPENREALTIME_PERSONAL_MOTION_PATH;
  if (process.env.NODE_ENV === "production" && (!configured || !path.isAbsolute(configured))) {
    throw new Error("个人动作素材库尚未配置持久化路径");
  }
  return configured || path.join(process.cwd(), ".openrealtime", "personal-motion");
}

export function personalLibraryOwnerDir(user: WebUser) {
  const owner = createHash("sha256").update(`${user.issuer}\0${user.subject}`).digest("hex");
  return path.join(libraryRoot(), owner);
}

export function personalMotionId(taskId: string) {
  return createHash("sha256").update(taskId).digest("hex");
}

export async function savePersonalMotion(user: WebUser, taskId: string, prompt: string, duration: number, bytes: Uint8Array) {
  if (!bytes.byteLength) throw new Error("视频内容为空");
  const dir = personalLibraryOwnerDir(user);
  const id = personalMotionId(taskId);
  const metadataPath = path.join(dir, `${id}.json`);
  const videoPath = path.join(dir, `${id}.mp4`);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  try {
    const existing = JSON.parse(await readFile(metadataPath, "utf8")) as PersonalMotionAsset;
    if (existing.id === id && existing.taskId === taskId) return existing;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  const record: PersonalMotionAsset = { id, taskId, prompt, duration, createdAt: new Date().toISOString() };
  const suffix = `${process.pid}-${crypto.randomUUID()}`;
  const temporaryVideo = `${videoPath}.${suffix}.tmp`;
  const temporaryMetadata = `${metadataPath}.${suffix}.tmp`;
  await writeFile(temporaryVideo, bytes, { mode: 0o600 });
  await rename(temporaryVideo, videoPath);
  await writeFile(temporaryMetadata, JSON.stringify(record), { mode: 0o600 });
  await rename(temporaryMetadata, metadataPath);
  return record;
}

export async function listPersonalMotions(user: WebUser): Promise<PersonalMotionAsset[]> {
  const dir = personalLibraryOwnerDir(user);
  const names = await readdir(dir).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return [];
    throw error;
  });
  const records = await Promise.all(names.filter(name => /^[a-f0-9]{64}\.json$/.test(name)).map(async name => {
    const record = JSON.parse(await readFile(path.join(dir, name), "utf8")) as PersonalMotionAsset;
    return record.id === name.slice(0, -5) ? record : null;
  }));
  return records.filter((record): record is PersonalMotionAsset => Boolean(record)).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function readPersonalMotionVideo(user: WebUser, id: string) {
  if (!/^[a-f0-9]{64}$/.test(id)) return null;
  try {
    return await readFile(path.join(personalLibraryOwnerDir(user), `${id}.mp4`));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export async function findPersonalMotion(user: WebUser, id: string): Promise<PersonalMotionAsset | null> {
  if (!/^[a-f0-9]{64}$/.test(id)) return null;
  try {
    const record = JSON.parse(await readFile(path.join(personalLibraryOwnerDir(user), `${id}.json`), "utf8")) as PersonalMotionAsset;
    return record.id === id ? record : null;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}
