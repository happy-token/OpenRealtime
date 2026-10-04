import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import type { TranscriptEntry } from "@/voice/session/transcript";

export type ConversationHistoryItem = {
  id: string;
  owner_id: string;
  role_id: string | null;
  role_name: string;
  mode: string;
  title: string;
  title_customized?: boolean;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  entries: TranscriptEntry[];
  thread_id?: string | null;
  voice_session_id?: string | null;
};

const ID = /^[a-f0-9-]{36}$/i;
const MAX_ENTRIES = 500;
const MAX_TEXT = 12_000;

export function conversationHistoryRoot() {
  return path.resolve(process.env.CONVERSATION_HISTORY_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "conversations"));
}

export function conversationRetentionDays() {
  const days = Number(process.env.VOICEAGENT_CONVERSATION_RETENTION_DAYS);
  return Number.isInteger(days) && days > 0 ? days : null;
}

function retained(items: ConversationHistoryItem[], now = Date.now()) {
  const days = conversationRetentionDays();
  return days === null ? items : items.filter((item) => Date.parse(item.updated_at) >= now - days * 86_400_000);
}

async function readItems(root: string) {
  try {
    const value = JSON.parse(await readFile(path.join(root, "conversations.json"), "utf8")) as unknown;
    if (!Array.isArray(value)) throw new Error("对话历史目录损坏");
    return retained(value as ConversationHistoryItem[]);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeItems(root: string, items: ConversationHistoryItem[]) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `conversations-${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(items), { mode: 0o600 });
  await rename(temporary, path.join(root, "conversations.json"));
}

export function validateConversationEntries(value: unknown): TranscriptEntry[] {
  if (!Array.isArray(value) || value.length > MAX_ENTRIES) throw new Error("对话内容无效");
  return value.map((entry) => {
    if (!entry || typeof entry !== "object") throw new Error("对话内容无效");
    const candidate = entry as Partial<TranscriptEntry>;
    if ((candidate.role !== "user" && candidate.role !== "assistant") || typeof candidate.text !== "string" || candidate.text.length > MAX_TEXT) throw new Error("对话内容无效");
    return {
      role: candidate.role,
      text: candidate.text,
      ...(typeof candidate.turnId === "string" ? { turnId: candidate.turnId.slice(0, 160) } : {}),
      ...(typeof candidate.generation === "number" && Number.isSafeInteger(candidate.generation) ? { generation: candidate.generation } : {}),
      ...(typeof candidate.revision === "number" && Number.isSafeInteger(candidate.revision) ? { revision: candidate.revision } : {}),
      ...(typeof candidate.isFinal === "boolean" ? { isFinal: candidate.isFinal } : {}),
      ...(candidate.status === "streaming" || candidate.status === "completed" || candidate.status === "interrupted" || candidate.status === "failed" ? { status: candidate.status } : {}),
    };
  });
}

export async function listConversations(ownerId: string, root = conversationHistoryRoot()) {
  return (await readItems(root)).filter((item) => item.owner_id === ownerId)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map((item) => ({ id: item.id, role_id: item.role_id, role_name: item.role_name,
      mode: item.mode, title: item.title, started_at: item.started_at, updated_at: item.updated_at,
      ended_at: item.ended_at, entry_count: item.entries.length }));
}

export async function getConversation(ownerId: string, id: string, root = conversationHistoryRoot()) {
  if (!ID.test(id)) return null;
  return (await readItems(root)).find((item) => item.owner_id === ownerId && item.id === id) ?? null;
}

export async function saveConversation(ownerId: string, input: {
  id: string; roleId: string | null; roleName: string; mode: string; entries: unknown; ended: boolean;
  threadId?: string | null; voiceSessionId?: string | null;
}, root = conversationHistoryRoot()) {
  for (const id of [input.threadId, input.voiceSessionId]) {
    if (id != null && (typeof id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(id))) throw new Error("运行时会话信息无效");
  }
  if (Boolean(input.threadId) !== Boolean(input.voiceSessionId)) throw new Error("运行时会话信息无效");
  if (!ID.test(input.id) || (input.roleId !== null && (typeof input.roleId !== "string" || input.roleId.length > 160))
    || typeof input.roleName !== "string" || input.roleName.length > 120
    || typeof input.mode !== "string" || input.mode.length > 40 || typeof input.ended !== "boolean") throw new Error("对话信息无效");
  const entries = validateConversationEntries(input.entries);
  if (!entries.length) throw new Error("对话内容为空");
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const index = items.findIndex((item) => item.id === input.id && item.owner_id === ownerId);
    if (items.some((item) => item.id === input.id && item.owner_id !== ownerId)) throw new Error("对话 ID 已被使用");
    const previous = index >= 0 ? items[index] : null;
    if (previous && (previous.role_id !== input.roleId || previous.mode !== input.mode
      || (previous.thread_id && input.threadId && previous.thread_id !== input.threadId))) throw new Error("对话身份无效，请新建对话");
    const now = new Date().toISOString();
    const firstText = entries.find((entry) => entry.role === "user" && entry.text.trim())?.text.trim()
      ?? entries.find((entry) => entry.text.trim())?.text.trim() ?? "新对话";
    const item: ConversationHistoryItem = {
      id: input.id, owner_id: ownerId, role_id: input.roleId, role_name: input.roleName || "默认助手",
      mode: input.mode, title: previous?.title_customized ? previous.title : firstText.slice(0, 60),
      ...(previous?.title_customized ? { title_customized: true } : {}), started_at: previous?.started_at ?? now,
      updated_at: now, ended_at: input.ended ? now : null, entries,
      thread_id: input.threadId ?? previous?.thread_id ?? null,
      voice_session_id: input.voiceSessionId ?? previous?.voice_session_id ?? null,
    };
    if (index >= 0) items[index] = item;
    else items.push(item);
    await writeItems(root, items);
    return item;
  });
}

export async function deleteConversation(ownerId: string, id: string, root = conversationHistoryRoot()) {
  if (!ID.test(id)) return false;
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const next = items.filter((item) => item.owner_id !== ownerId || item.id !== id);
    if (next.length === items.length) return false;
    await writeItems(root, next);
    return true;
  });
}

export async function renameConversation(ownerId: string, id: string, title: string, root = conversationHistoryRoot()) {
  if (typeof title !== "string" || !title.trim() || title.trim().length > 80 || /[\r\n]/.test(title)) throw new Error("对话名称需为 1–80 个字符，不能换行");
  if (!ID.test(id)) return null;
  return withAvatarCatalogLock(root, async () => {
    const items = await readItems(root);
    const item = items.find((entry) => entry.owner_id === ownerId && entry.id === id);
    if (!item) return null;
    item.title = title.trim();
    item.title_customized = true;
    await writeItems(root, items);
    return item;
  });
}
