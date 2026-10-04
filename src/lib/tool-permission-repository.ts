import { randomUUID } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { isToolPermissionMode, type ToolPermissionMode, type ToolPermissionSettings } from "./tool-permission-types";

type RecordEntry = {
  owner_id: string;
  mode: ToolPermissionMode;
  role_overrides: Record<string, ToolPermissionMode>;
  updated_at: string;
};
const ROLE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;

export function toolPermissionsRoot() {
  return path.resolve(process.env.VOICEAGENT_TOOL_PERMISSIONS_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "tool-permissions"));
}

async function readRecords(root: string): Promise<RecordEntry[]> {
  let parsed: unknown;
  try { parsed = JSON.parse(await readFile(path.join(root, "settings.json"), "utf8")); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  const payload = parsed as { version?: unknown; records?: unknown } | null;
  if (!payload || payload.version !== 1 || !Array.isArray(payload.records)) throw new Error("工具权限配置损坏");
  const owners = new Set<string>();
  for (const item of payload.records) {
    const record = item as Partial<RecordEntry> | null;
    if (!record || typeof record.owner_id !== "string" || !record.owner_id || owners.has(record.owner_id)
      || !isToolPermissionMode(record.mode) || typeof record.updated_at !== "string"
      || !record.role_overrides || typeof record.role_overrides !== "object" || Array.isArray(record.role_overrides)
      || Object.entries(record.role_overrides).some(([id, mode]) => !ROLE_ID.test(id) || !isToolPermissionMode(mode))) throw new Error("工具权限配置损坏");
    owners.add(record.owner_id);
  }
  return payload.records as RecordEntry[];
}

function toSettings(record?: RecordEntry): ToolPermissionSettings {
  return record ? { mode: record.mode, roleOverrides: { ...record.role_overrides }, updatedAt: record.updated_at }
    : { mode: "full", roleOverrides: {}, updatedAt: null };
}

export async function getToolPermissions(ownerId: string, root = toolPermissionsRoot()) {
  return toSettings((await readRecords(root)).find((record) => record.owner_id === ownerId));
}

export async function saveToolPermissions(ownerId: string, mode: ToolPermissionMode | null, roleId: string | null = null, root = toolPermissionsRoot()) {
  if (!ownerId || (mode !== null && !isToolPermissionMode(mode)) || (roleId !== null && !ROLE_ID.test(roleId)) || (roleId === null && mode === null)) throw new Error("工具权限配置无效");
  return withAvatarCatalogLock(root, async () => {
    const records = await readRecords(root);
    const current = records.find((record) => record.owner_id === ownerId);
    const record: RecordEntry = current ? { ...current, role_overrides: { ...current.role_overrides } }
      : { owner_id: ownerId, mode: "full", role_overrides: {}, updated_at: "" };
    if (roleId !== null) {
      if (mode === null) delete record.role_overrides[roleId];
      else record.role_overrides[roleId] = mode;
      if (Object.keys(record.role_overrides).length > 100) throw new Error("角色权限配置超过上限");
    } else record.mode = mode!;
    record.updated_at = new Date().toISOString();
    const next = records.filter((item) => item.owner_id !== ownerId);
    next.push(record);
    const temporary = path.join(root, `settings-${randomUUID()}.tmp`);
    await writeFile(temporary, JSON.stringify({ version: 1, records: next }), { mode: 0o600 });
    await rename(temporary, path.join(root, "settings.json"));
    return toSettings(record);
  });
}
