import { randomUUID } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { hostedAvatarRoleId } from "./hosted-avatar-role-id";

type SettingsRecord = { owner_id: string; avatar_id: string; memory_enabled: boolean; tool_ids: string[] };

export function hostedAvatarSettingsRoot() {
  return path.resolve(process.env.HOSTED_AVATAR_SETTINGS_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "hosted-avatar-settings"));
}

async function readRecords(root: string): Promise<SettingsRecord[]> {
  try {
    const parsed = JSON.parse(await readFile(path.join(root, "settings.json"), "utf8")) as unknown;
    if (!Array.isArray(parsed)) throw new Error("实时数字人配置损坏");
    return parsed as SettingsRecord[];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export async function getHostedAvatarSettings(ownerId: string, avatarId: string, root = hostedAvatarSettingsRoot()) {
  hostedAvatarRoleId(avatarId);
  return (await readRecords(root)).find((item) => item.owner_id === ownerId && item.avatar_id === avatarId) ?? null;
}

export async function saveHostedAvatarSettings(ownerId: string, avatarId: string, memoryEnabled: boolean, toolIds: string[] = [], root = hostedAvatarSettingsRoot()) {
  hostedAvatarRoleId(avatarId);
  if (toolIds.length > 50 || toolIds.some((id) => typeof id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(id))) throw new Error("工具 ID 无效");
  return withAvatarCatalogLock(root, async () => {
    const records = await readRecords(root);
    const record: SettingsRecord = { owner_id: ownerId, avatar_id: avatarId, memory_enabled: memoryEnabled, tool_ids: [...new Set(toolIds)] };
    const next = records.filter((item) => item.owner_id !== ownerId || item.avatar_id !== avatarId);
    next.push(record);
    const temporary = path.join(root, `settings-${randomUUID()}.tmp`);
    await writeFile(temporary, JSON.stringify(next), { mode: 0o600 });
    await rename(temporary, path.join(root, "settings.json"));
    return record;
  });
}
