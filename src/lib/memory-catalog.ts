import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";

export type MemoryKind = "preference" | "relationship" | "goal" | "correction";
export type MemoryRecord = {
  id: string; owner_id: string; role_id: string; kind: MemoryKind;
  content: string; source_conversation_id: string | null; created_at: string; updated_at: string;
};
const ROLE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;
const MEMORY_KINDS: MemoryKind[] = ["preference", "relationship", "goal", "correction"];

export function memoryRoot() {
  return path.resolve(process.env.VOICEAGENT_MEMORY_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "memory"));
}

function validate(roleId: string, content?: unknown) {
  if (typeof roleId !== "string" || !ROLE_ID.test(roleId)) throw new Error("角色 ID 无效");
  if (content !== undefined && (typeof content !== "string" || !content.trim() || content.length > 300 || containsSensitiveContent(content))) throw new Error("记忆内容无效或包含敏感信息");
}

export function containsSensitiveContent(text: string) {
  return /(?:密码|验证码|密钥|token|api\s*key|银行卡|身份证|护照|病历|诊断|住址|详细地址|电话号码|手机号|邮箱|email|信用卡|cvv)/i.test(text)
    || /\b1[3-9]\d{9}\b|\b\d{15,18}[0-9xX]?\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/.test(text);
}

async function readItems(root: string): Promise<MemoryRecord[]> {
  try {
    const value = JSON.parse(await readFile(path.join(root, "memories.json"), "utf8")) as unknown;
    if (!Array.isArray(value)) throw new Error("记忆目录损坏");
    return value as MemoryRecord[];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeItems(root: string, items: MemoryRecord[]) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `memories-${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(items), { mode: 0o600 });
  await rename(temporary, path.join(root, "memories.json"));
}

export async function listMemories(ownerId: string, roleId: string, root = memoryRoot()) {
  validate(roleId);
  return (await readItems(root)).filter((item) => item.owner_id === ownerId && item.role_id === roleId)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export async function addMemory(ownerId: string, roleId: string, kind: MemoryKind, content: string,
  sourceConversationId: string | null = null, root = memoryRoot()) {
  validate(roleId, content);
  if (typeof content !== "string") throw new Error("记忆内容无效");
  if (!MEMORY_KINDS.includes(kind)) throw new Error("记忆类型无效");
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const clean = content.trim();
    const duplicate = items.find((item) => item.owner_id === ownerId && item.role_id === roleId && item.content === clean);
    if (duplicate) return duplicate;
    if (items.filter((item) => item.owner_id === ownerId && item.role_id === roleId).length >= 100) throw new Error("角色记忆已达到上限");
    const now = new Date().toISOString();
    const item: MemoryRecord = { id: randomUUID(), owner_id: ownerId, role_id: roleId, kind, content: clean,
      source_conversation_id: sourceConversationId, created_at: now, updated_at: now };
    items.push(item);
    await writeItems(root, items);
    return item;
  });
}

export async function updateMemory(ownerId: string, roleId: string, id: string, content: string, root = memoryRoot()) {
  validate(roleId, content);
  if (typeof content !== "string") throw new Error("记忆内容无效");
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const index = items.findIndex((item) => item.id === id && item.owner_id === ownerId && item.role_id === roleId);
    if (index < 0) return null;
    items[index] = { ...items[index], content: content.trim(), updated_at: new Date().toISOString() };
    await writeItems(root, items);
    return items[index];
  });
}

export async function removeMemory(ownerId: string, roleId: string, id: string | null, root = memoryRoot()) {
  validate(roleId);
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const next = items.filter((item) => item.owner_id !== ownerId || item.role_id !== roleId || (id !== null && item.id !== id));
    if (next.length === items.length) return false;
    await writeItems(root, next);
    return true;
  });
}

export function extractMemories(text: string): Array<{ kind: MemoryKind; content: string }> {
  const clean = text.trim();
  if (!clean || clean.length > 300 || containsSensitiveContent(clean)) return [];
  const patterns: Array<[MemoryKind, RegExp]> = [
    ["preference", /^(?:我(?:很)?喜欢|我不喜欢|我偏好|我习惯)(.{2,100})[。.!！]?$/],
    ["goal", /^(?:我的目标是|我打算长期|我正在努力)(.{2,100})[。.!！]?$/],
    ["correction", /^(?:纠正一下|以后请记住|请记住)(.{2,100})[。.!！]?$/],
    ["relationship", /^(?:我和(?:家人|朋友|同事|伴侣))(.{2,100})[。.!！]?$/],
  ];
  return patterns.flatMap(([kind, pattern]) => pattern.test(clean) ? [{ kind, content: clean }] : []);
}
