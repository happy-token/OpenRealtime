import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import { listOwnedAvatars } from "./avatar-catalog-repository";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { listPersonas } from "./avatar-persona-server";
import {
  isRolePresentationMode,
  isRoleVoiceDialect,
  isRoleDefaultSelections,
  enabledRoleModesForAvatar,
  preferredRoleMode,
  roleModesForAvatar,
  type RolePresentationMode,
  type RoleDefaultSelections,
  type RoleRecord,
  type RoleVoiceDialect,
} from "./role-records";

const ROLE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;
const DEFAULT_ROLE_ID = "default-assistant";
const LEGACY_DEFAULT_TOOL_IDS = ["tool-current-time", "tool-web-search"];

type StoredRole = Omit<RoleRecord, "avatar_image_url" | "persona_name">;

export async function listRoles(root = repositoryRoot()): Promise<RoleRecord[]> {
  const [stored, avatars, personas] = await Promise.all([readCatalog(root), listOwnedAvatars(), listPersonas()]);
  const migrated = migratedRolesFrom(avatars, personas);
  const byId = new Map(migrated.map((role) => [role.role_id, role]));
  for (const role of stored) byId.set(role.role_id, hydrateStoredRole(role, migrated, personas, avatars));
  return [...byId.values()]
    .filter((role) => !role.deleted_at)
    .sort((left, right) => {
      if (left.role_id === DEFAULT_ROLE_ID) return -1;
      if (right.role_id === DEFAULT_ROLE_ID) return 1;
      return right.updated_at.localeCompare(left.updated_at);
    });
}

export async function findRole(roleId: string, root = repositoryRoot()) {
  validateRoleId(roleId);
  return (await listRoles(root)).find((role) => role.role_id === roleId) ?? null;
}

export async function createRole(
  input: {
    displayName: string;
    voiceProvider?: "bailian" | "doubao";
    voiceId?: string;
    voiceDialect?: RoleVoiceDialect;
    personaId?: string | null;
    avatarId?: string | null;
    enabledModes?: RolePresentationMode[];
    defaultMode?: RolePresentationMode;
    defaultSelections?: RoleDefaultSelections;
    memoryEnabled?: boolean;
    modelId?: string | null;
    toolIds?: string[];
  },
  root = repositoryRoot(),
) {
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const now = new Date().toISOString();
    const enabledModes = normalizeModes(input.enabledModes ?? ["conversation"]);
    const defaultMode = input.defaultMode && enabledModes.includes(input.defaultMode)
      ? input.defaultMode
      : preferredRoleMode(enabledModes);
    const role: StoredRole = {
      role_id: `role-${randomUUID()}`,
      display_name: normalizeName(input.displayName),
      avatar_id: normalizeOptionalId(input.avatarId ?? null),
      persona_id: normalizeOptionalId(input.personaId ?? null),
      voice_provider: input.voiceProvider === "doubao" ? "doubao" : "bailian",
      voice_id: normalizeVoiceId(input.voiceId),
      voice_dialect: input.voiceDialect ?? "",
      enabled_modes: enabledModes,
      default_mode: defaultMode,
      default_selections: input.defaultSelections ?? {},
      memory_enabled: input.memoryEnabled ?? true,
      model_id: normalizeModelId(input.modelId),
      tool_ids: normalizeResourceIds(input.toolIds ?? []),
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    await writeCatalog(root, [...records, role]);
    const [personas, avatars] = await Promise.all([listPersonas(), listOwnedAvatars()]);
    return hydrateStoredRole(role, [], personas, avatars);
  });
}

export async function updateRole(
  roleId: string,
  update: {
    displayName?: string;
    voiceProvider?: "bailian" | "doubao";
    voiceId?: string;
    voiceDialect?: RoleVoiceDialect;
    personaId?: string | null;
    avatarId?: string | null;
    enabledModes?: RolePresentationMode[];
    defaultMode?: RolePresentationMode;
    defaultSelections?: RoleDefaultSelections;
    memoryEnabled?: boolean;
    modelId?: string | null;
    toolIds?: string[];
  },
  root = repositoryRoot(),
) {
  validateRoleId(roleId);
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((role) => role.role_id === roleId)
      ?? storedFromHydrated(await findMigratedRole(roleId));
    if (!current) throw new Error("找不到这个角色");
    const enabledModes = update.enabledModes
      ? normalizeModes(update.enabledModes)
      : current.enabled_modes;
    const requestedDefault = update.defaultMode ?? current.default_mode;
    const defaultMode = enabledModes.includes(requestedDefault) ? requestedDefault : preferredRoleMode(enabledModes);
    const next: StoredRole = {
      ...current,
      ...(update.displayName !== undefined ? { display_name: normalizeName(update.displayName) } : {}),
      ...(update.voiceProvider !== undefined ? { voice_provider: update.voiceProvider } : {}),
      ...(update.voiceId !== undefined ? { voice_id: normalizeVoiceId(update.voiceId) } : {}),
      ...(update.voiceDialect !== undefined ? { voice_dialect: update.voiceDialect } : {}),
      ...(update.personaId !== undefined ? { persona_id: normalizeOptionalId(update.personaId) } : {}),
      ...(update.avatarId !== undefined ? { avatar_id: normalizeOptionalId(update.avatarId) } : {}),
      ...(update.memoryEnabled !== undefined ? { memory_enabled: update.memoryEnabled } : {}),
      ...(update.modelId !== undefined ? { model_id: normalizeModelId(update.modelId) } : {}),
      ...(update.toolIds !== undefined ? { tool_ids: normalizeResourceIds(update.toolIds) } : {}),
      enabled_modes: enabledModes,
      default_mode: defaultMode,
      ...(update.defaultSelections !== undefined ? { default_selections: update.defaultSelections } : {}),
      updated_at: new Date().toISOString(),
    };
    await writeCatalog(root, [...records.filter((role) => role.role_id !== roleId), next]);
    const [avatars, personas] = await Promise.all([listOwnedAvatars(), listPersonas()]);
    return hydrateStoredRole(next, migratedRolesFrom(avatars, personas), personas, avatars);
  });
}

export async function deleteRole(roleId: string, root = repositoryRoot()) {
  validateRoleId(roleId);
  if (roleId === DEFAULT_ROLE_ID) throw new Error("默认助手不能删除");
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((role) => role.role_id === roleId)
      ?? storedFromHydrated(await findMigratedRole(roleId));
    if (!current || current.deleted_at) return false;
    const now = new Date().toISOString();
    const deleted: StoredRole = { ...current, updated_at: now, deleted_at: now };
    await writeCatalog(root, [...records.filter((role) => role.role_id !== roleId), deleted]);
    return true;
  });
}

async function migratedRoles(): Promise<RoleRecord[]> {
  const [avatars, personas] = await Promise.all([listOwnedAvatars(), listPersonas()]);
  return migratedRolesFrom(avatars, personas);
}

function migratedRolesFrom(
  avatars: Awaited<ReturnType<typeof listOwnedAvatars>>,
  personas: Awaited<ReturnType<typeof listPersonas>>,
): RoleRecord[] {
  const personaByAvatar = new Map(personas.flatMap((persona) => (
    persona.linkedAvatarIds.map((avatarId) => [avatarId, persona] as const)
  )));
  const now = new Date(0).toISOString();
  const defaultRole: RoleRecord = {
    role_id: DEFAULT_ROLE_ID,
    display_name: "默认助手",
    avatar_id: null,
    avatar_image_url: null,
    persona_id: null,
    persona_name: null,
    voice_provider: "bailian",
    voice_id: "__active_bailian_clone__",
    voice_dialect: "",
    enabled_modes: ["conversation"],
    default_mode: "conversation",
    default_selections: {},
    memory_enabled: true,
    tool_ids: LEGACY_DEFAULT_TOOL_IDS,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
  const linkedRoles = avatars.flatMap((avatar): RoleRecord[] => {
    if (avatar.deleted_at) return [];
    const persona = personaByAvatar.get(avatar.avatar_id);
    if (!persona) return [];
    const enabledModes = roleModesForAvatar(avatar);
    const defaultMode = preferredRoleMode(enabledModes);
    return [{
      role_id: `role-${avatar.avatar_id}`,
      display_name: avatar.display_name,
      avatar_id: avatar.avatar_id,
      avatar_image_url: avatar.source_image_url,
      persona_id: persona.personaId,
      persona_name: persona.personaName,
      voice_provider: "bailian",
      voice_id: "__active_bailian_clone__",
      voice_dialect: "",
      enabled_modes: enabledModes,
      default_mode: defaultMode,
      default_selections: {},
      memory_enabled: true,
      tool_ids: LEGACY_DEFAULT_TOOL_IDS,
      created_at: avatar.created_at,
      updated_at: avatar.updated_at,
      deleted_at: null,
    }];
  });
  return [defaultRole, ...linkedRoles];
}

async function findMigratedRole(roleId: string) {
  return (await migratedRoles()).find((role) => role.role_id === roleId) ?? null;
}

function hydrateStoredRole(
  role: StoredRole,
  migrated: RoleRecord[],
  personas: Awaited<ReturnType<typeof listPersonas>>,
  avatars: Awaited<ReturnType<typeof listOwnedAvatars>>,
): RoleRecord {
  const source = migrated.find((candidate) => candidate.role_id === role.role_id)
    ?? migrated.find((candidate) => candidate.avatar_id && candidate.avatar_id === role.avatar_id);
  const avatar = avatars.find((candidate) => candidate.avatar_id === role.avatar_id && !candidate.deleted_at) ?? null;
  const enabledModes = enabledRoleModesForAvatar(role.enabled_modes, avatar);
  return {
    ...role,
    avatar_image_url: avatar?.source_image_url ?? source?.avatar_image_url ?? null,
    persona_name: personas.find((persona) => persona.personaId === role.persona_id)?.personaName
      ?? (source?.persona_id === role.persona_id ? source.persona_name : null),
    enabled_modes: enabledModes,
    default_mode: enabledModes.includes(role.default_mode) ? role.default_mode : preferredRoleMode(enabledModes),
    default_selections: role.default_selections ?? {},
    voice_dialect: role.voice_dialect ?? "",
    tool_ids: role.tool_ids ?? LEGACY_DEFAULT_TOOL_IDS,
  };
}

function storedFromHydrated(role: RoleRecord | null): StoredRole | null {
  if (!role) return null;
  return {
    role_id: role.role_id,
    display_name: role.display_name,
    avatar_id: role.avatar_id,
    persona_id: role.persona_id,
    voice_provider: role.voice_provider,
    voice_id: role.voice_id,
    voice_dialect: role.voice_dialect ?? "",
    enabled_modes: role.enabled_modes,
    default_mode: role.default_mode,
    default_selections: role.default_selections ?? {},
    memory_enabled: role.memory_enabled,
    model_id: role.model_id ?? null,
    tool_ids: role.tool_ids,
    created_at: role.created_at,
    updated_at: role.updated_at,
    deleted_at: role.deleted_at,
  };
}

function normalizeModes(modes: RolePresentationMode[]) {
  const normalized = [...new Set(modes.filter(isRolePresentationMode))];
  if (!normalized.includes("conversation")) normalized.unshift("conversation");
  return normalized;
}

function normalizeName(value: string) {
  const name = value.trim();
  if (!name || name.length > 80 || /[\r\n]/.test(name)) throw new Error("角色名称无效");
  return name;
}

function normalizeVoiceId(value?: string) {
  const voiceId = value?.trim() || DEFAULT_TTS_VOICE;
  if (!/^[A-Za-z0-9_-]{2,128}$/.test(voiceId)) throw new Error("声音 ID 无效");
  return voiceId;
}

function normalizeModelId(value?: string | null) {
  if (value == null || !value.trim()) return null;
  const id = value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/-]{1,119}$/.test(id)) throw new Error("模型 ID 无效");
  return id;
}

function normalizeOptionalId(value: string | null) {
  if (value === null) return null;
  const id = value.trim();
  if (!id || id.length > 160 || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(id)) throw new Error("资源 ID 无效");
  return id;
}

function normalizeResourceIds(values: string[]) {
  return [...new Set(values.map((value) => {
    const id = normalizeOptionalId(value);
    if (id === null) throw new Error("资源 ID 无效");
    return id;
  }))];
}

function validateRoleId(roleId: string) {
  if (!ROLE_ID.test(roleId)) throw new Error("角色 ID 无效");
}

function repositoryRoot() {
  return path.resolve(process.env.ROLE_CATALOG_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "role-catalog"));
}

function catalogPath(root: string) {
  return path.join(root, "roles.json");
}

async function readCatalog(root: string): Promise<StoredRole[]> {
  try {
    const value = JSON.parse(await readFile(catalogPath(root), "utf8")) as unknown;
    if (!Array.isArray(value) || !value.every(isStoredRole)) throw new Error("角色目录结构异常");
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeCatalog(root: string, records: StoredRole[]) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `roles.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(records, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, catalogPath(root));
}

function isStoredRole(value: unknown): value is StoredRole {
  if (!value || typeof value !== "object") return false;
  const role = value as StoredRole;
  return ROLE_ID.test(role.role_id)
    && typeof role.display_name === "string"
    && (role.avatar_id === null || typeof role.avatar_id === "string")
    && (role.persona_id === null || typeof role.persona_id === "string")
    && (role.voice_provider === "bailian" || role.voice_provider === "doubao")
    && typeof role.voice_id === "string"
    && (role.voice_dialect === undefined || isRoleVoiceDialect(role.voice_dialect))
    && Array.isArray(role.enabled_modes)
    && role.enabled_modes.every(isRolePresentationMode)
    && isRolePresentationMode(role.default_mode)
    && (role.default_selections === undefined || isRoleDefaultSelections(role.default_selections))
    && typeof role.memory_enabled === "boolean"
    && (role.model_id === undefined || role.model_id === null || (typeof role.model_id === "string" && role.model_id.length <= 120))
    && (role.tool_ids === undefined || (Array.isArray(role.tool_ids) && role.tool_ids.every((item) => typeof item === "string")))
    && typeof role.created_at === "string"
    && typeof role.updated_at === "string"
    && (role.deleted_at === null || typeof role.deleted_at === "string");
}
