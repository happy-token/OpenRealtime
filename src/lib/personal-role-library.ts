import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { findOwnedAvatar } from "./avatar-catalog-repository";
import { listPersonas } from "./avatar-persona-server";
import { findPersonalAvatar } from "./personal-avatar-library";
import { personalLibraryOwnerDir } from "./personal-motion-library";
import { enabledRoleModesForAvatar, isRoleDefaultSelections, isRolePresentationMode, isRoleVoiceDialect, preferredRoleMode, roleModesForAvatar, type RoleDefaultSelections, type RolePresentationMode, type RoleRecord, type RoleVoiceDialect } from "./role-records";
import type { WebUser } from "./user-session";

const PERSONAL_ROLE_ID = /^role-personal-[a-f0-9-]{36}$/;
type StoredPersonalRole = Omit<RoleRecord, "avatar_image_url" | "persona_name" | "enabled_modes"> & {
  enabled_modes?: RolePresentationMode[];
};
export type PersonalRoleInput = {
  displayName: string;
  voiceProvider: "bailian" | "doubao";
  voiceId: string;
  voiceDialect?: RoleVoiceDialect;
  asrProvider?: RoleRecord["asr_provider"];
  llmProvider?: RoleRecord["llm_provider"];
  avatarId: string | null;
  personaId?: string | null;
  enabledModes: RolePresentationMode[];
  defaultMode: RolePresentationMode;
  defaultSelections?: RoleDefaultSelections;
  memoryEnabled: boolean;
  modelId?: string | null;
  toolIds?: string[];
};

function roleDir(user: WebUser) { return path.join(personalLibraryOwnerDir(user), "roles"); }
function catalogFile(dir: string) { return path.join(dir, "catalog.json"); }

async function readCatalog(dir: string): Promise<StoredPersonalRole[]> {
  try {
    const records = JSON.parse(await readFile(catalogFile(dir), "utf8")) as unknown;
    if (!Array.isArray(records) || !records.every(isStoredRole)) throw new Error("个人角色目录结构异常");
    return records;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeCatalog(dir: string, records: StoredPersonalRole[]) {
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const temporary = path.join(dir, `catalog.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(records, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, catalogFile(dir));
}

async function hydrate(user: WebUser, record: StoredPersonalRole): Promise<RoleRecord> {
  const personalAvatar = record.avatar_id?.startsWith("avatar-personal-") ? await findPersonalAvatar(user, record.avatar_id) : null;
  const sharedAvatar = record.avatar_id && !record.avatar_id.startsWith("avatar-personal-") ? await findOwnedAvatar(record.avatar_id) : null;
  const activeAvatar = personalAvatar && !personalAvatar.deletedAt ? {
    avatar_id: personalAvatar.id,
    display_name: personalAvatar.name,
    source_image_url: `/api/user/avatars/${personalAvatar.id}/image`,
    created_at: personalAvatar.createdAt,
    updated_at: personalAvatar.updatedAt,
    deleted_at: personalAvatar.deletedAt,
    realtime_binding: null,
    actions: personalAvatar.actions,
  } : sharedAvatar && !sharedAvatar.deleted_at ? sharedAvatar : null;
  const enabledModes = record.enabled_modes
    ? enabledRoleModesForAvatar(record.enabled_modes, activeAvatar)
    : roleModesForAvatar(activeAvatar);
  const persona = record.persona_id ? (await listPersonas()).find((item) => item.personaId === record.persona_id) : null;
  return {
    ...record,
    avatar_id: activeAvatar?.avatar_id ?? null,
    avatar_image_url: activeAvatar?.source_image_url ?? null,
    persona_id: record.persona_id ?? null,
    persona_name: persona?.personaName ?? null,
    tool_ids: record.tool_ids ?? [],
    enabled_modes: enabledModes,
    default_mode: enabledModes.includes(record.default_mode) ? record.default_mode : preferredRoleMode(enabledModes),
    default_selections: record.default_selections ?? {},
    voice_dialect: record.voice_dialect ?? "",
  };
}

export async function listPersonalRoles(user: WebUser): Promise<RoleRecord[]> {
  const records = (await readCatalog(roleDir(user))).filter((record) => !record.deleted_at);
  return Promise.all(records.sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map((record) => hydrate(user, record)));
}

export async function findPersonalRole(user: WebUser, roleId: string): Promise<RoleRecord | null> {
  if (!PERSONAL_ROLE_ID.test(roleId)) return null;
  const record = (await readCatalog(roleDir(user))).find((item) => item.role_id === roleId && !item.deleted_at);
  return record ? hydrate(user, record) : null;
}

export async function createPersonalRole(user: WebUser, input: PersonalRoleInput): Promise<RoleRecord> {
  validateInput(input);
  await validateAvatar(user, input.avatarId, input.enabledModes);
  await validatePersona(input.personaId ?? null);
  const dir = roleDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    if (records.filter((record) => !record.deleted_at).length >= 100) throw new Error("个人角色数量已达上限");
    const now = new Date().toISOString();
    const record: StoredPersonalRole = {
      role_id: `role-personal-${randomUUID()}`,
      display_name: input.displayName.trim(),
      avatar_id: input.avatarId,
      persona_id: input.personaId ?? null,
      enabled_modes: input.enabledModes,
      default_mode: input.defaultMode,
      default_selections: input.defaultSelections ?? {},
      voice_provider: input.voiceProvider,
      voice_id: input.voiceId.trim(),
      voice_dialect: input.voiceDialect ?? "",
      asr_provider: input.asrProvider ?? null,
      llm_provider: input.llmProvider ?? null,
      memory_enabled: input.memoryEnabled,
      model_id: input.modelId?.trim() || null,
      tool_ids: input.toolIds ?? [],
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    await writeCatalog(dir, [...records, record]);
    return hydrate(user, record);
  });
}

export async function updatePersonalRole(user: WebUser, roleId: string, input: PersonalRoleInput): Promise<RoleRecord | null> {
  if (!PERSONAL_ROLE_ID.test(roleId)) return null;
  validateInput(input);
  await validateAvatar(user, input.avatarId, input.enabledModes);
  await validatePersona(input.personaId ?? null);
  const dir = roleDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const current = records.find((record) => record.role_id === roleId && !record.deleted_at);
    if (!current) return null;
    const next: StoredPersonalRole = {
      ...current,
      display_name: input.displayName.trim(),
      avatar_id: input.avatarId,
      persona_id: input.personaId ?? null,
      enabled_modes: input.enabledModes,
      default_mode: input.defaultMode,
      default_selections: input.defaultSelections ?? current.default_selections ?? {},
      voice_provider: input.voiceProvider,
      voice_id: input.voiceId.trim(),
      voice_dialect: input.voiceDialect ?? current.voice_dialect ?? "",
      asr_provider: input.asrProvider === undefined ? current.asr_provider ?? null : input.asrProvider,
      llm_provider: input.llmProvider === undefined ? current.llm_provider ?? null : input.llmProvider,
      memory_enabled: input.memoryEnabled,
      model_id: input.modelId === undefined ? current.model_id ?? null : input.modelId?.trim() || null,
      tool_ids: input.toolIds ?? current.tool_ids ?? [],
      updated_at: new Date().toISOString(),
    };
    await writeCatalog(dir, records.map((record) => record.role_id === roleId ? next : record));
    return hydrate(user, next);
  });
}

export async function deletePersonalRole(user: WebUser, roleId: string): Promise<boolean> {
  if (!PERSONAL_ROLE_ID.test(roleId)) return false;
  const dir = roleDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const current = records.find((record) => record.role_id === roleId && !record.deleted_at);
    if (!current) return false;
    const now = new Date().toISOString();
    await writeCatalog(dir, records.map((record) => record.role_id === roleId
      ? { ...record, updated_at: now, deleted_at: now }
      : record));
    return true;
  });
}

async function validateAvatar(user: WebUser, avatarId: string | null, modes: readonly RolePresentationMode[]) {
  if (avatarId === null) {
    if (modes.some((mode) => mode !== "conversation" && mode !== "realtime")) throw new Error("当前呈现方式无效");
    return;
  }
  const personalAvatar = avatarId.startsWith("avatar-personal-") ? await findPersonalAvatar(user, avatarId) : null;
  const sharedAvatar = avatarId.startsWith("avatar-personal-") ? null : await findOwnedAvatar(avatarId);
  const avatar = personalAvatar && !personalAvatar.deletedAt ? {
    avatar_id: personalAvatar.id, display_name: personalAvatar.name, source_image_url: "", created_at: personalAvatar.createdAt,
    updated_at: personalAvatar.updatedAt, deleted_at: personalAvatar.deletedAt, realtime_binding: null, actions: personalAvatar.actions,
  } : sharedAvatar && !sharedAvatar.deleted_at ? sharedAvatar : null;
  if (!avatar) throw new Error("数字人形象不可用");
  const available = roleModesForAvatar(avatar);
  if (modes.some((mode) => mode !== "realtime" && !available.includes(mode))) throw new Error("当前呈现方式无效");
}

async function validatePersona(personaId: string | null) {
  if (personaId && !(await listPersonas()).some((persona) => persona.personaId === personaId)) throw new Error("人设不可用");
}

function validateInput(input: PersonalRoleInput) {
  if (!input || typeof input.displayName !== "string" || !input.displayName.trim() || input.displayName.trim().length > 80 || /[\r\n]/.test(input.displayName)) throw new Error("角色名称无效");
  if (input.voiceProvider !== "bailian" && input.voiceProvider !== "doubao") throw new Error("声音供应商无效");
  if (typeof input.voiceId !== "string" || !/^[A-Za-z0-9_-]{2,128}$/.test(input.voiceId.trim())) throw new Error("声音 ID 无效");
  if (input.voiceDialect !== undefined && !isRoleVoiceDialect(input.voiceDialect)) throw new Error("声音方言无效");
  if (input.asrProvider !== undefined && input.asrProvider !== null && input.asrProvider !== "doubao" && input.asrProvider !== "dashscope") throw new Error("ASR 供应商无效");
  if (input.llmProvider !== undefined && input.llmProvider !== null && input.llmProvider !== "deepseek" && input.llmProvider !== "openai") throw new Error("LLM 供应商无效");
  if (input.avatarId !== null && (typeof input.avatarId !== "string" || !/^avatar-[A-Za-z0-9-]{3,80}$/.test(input.avatarId))) throw new Error("数字人 ID 无效");
  if (input.personaId !== undefined && input.personaId !== null && (typeof input.personaId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(input.personaId))) throw new Error("人设 ID 无效");
  if (!Array.isArray(input.enabledModes) || input.enabledModes.length === 0 || input.enabledModes.length > 4 || input.enabledModes.some((mode) => !isRolePresentationMode(mode) || mode === "motion")) throw new Error("呈现方式无效");
  if (!isRolePresentationMode(input.defaultMode)) throw new Error("当前呈现方式无效");
  if (!input.enabledModes.includes(input.defaultMode)) throw new Error("默认呈现方式无效");
  if (typeof input.memoryEnabled !== "boolean") throw new Error("记忆配置无效");
  if (input.defaultSelections !== undefined && !isRoleDefaultSelections(input.defaultSelections)) throw new Error("默认素材配置无效");
  if (input.modelId !== undefined && input.modelId !== null && (typeof input.modelId !== "string" || (input.modelId.trim() && !/^[A-Za-z0-9][A-Za-z0-9._:/-]{1,119}$/.test(input.modelId.trim())))) throw new Error("模型 ID 无效");
  if (input.toolIds !== undefined && (!Array.isArray(input.toolIds) || input.toolIds.length > 30 || input.toolIds.some((id) => typeof id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(id)))) throw new Error("工具配置无效");
}

function isStoredRole(value: unknown): value is StoredPersonalRole {
  if (!value || typeof value !== "object") return false;
  const role = value as Partial<StoredPersonalRole>;
  return typeof role.role_id === "string" && PERSONAL_ROLE_ID.test(role.role_id)
    && typeof role.display_name === "string"
    && (role.avatar_id === null || (typeof role.avatar_id === "string" && /^avatar-[A-Za-z0-9-]{3,80}$/.test(role.avatar_id)))
    && (role.persona_id === undefined || role.persona_id === null || (typeof role.persona_id === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(role.persona_id)))
    && (role.voice_provider === "bailian" || role.voice_provider === "doubao")
    && typeof role.voice_id === "string" && typeof role.memory_enabled === "boolean"
    && (role.voice_dialect === undefined || isRoleVoiceDialect(role.voice_dialect))
    && (role.asr_provider === undefined || role.asr_provider === null || role.asr_provider === "doubao" || role.asr_provider === "dashscope")
    && (role.llm_provider === undefined || role.llm_provider === null || role.llm_provider === "deepseek" || role.llm_provider === "openai")
    && (role.model_id === undefined || role.model_id === null || typeof role.model_id === "string")
    && (role.tool_ids === undefined || (Array.isArray(role.tool_ids) && role.tool_ids.every((id) => typeof id === "string")))
    && (role.enabled_modes === undefined || (Array.isArray(role.enabled_modes) && role.enabled_modes.length > 0 && role.enabled_modes.every(isRolePresentationMode)))
    && isRolePresentationMode(role.default_mode)
    && (role.default_selections === undefined || isRoleDefaultSelections(role.default_selections))
    && typeof role.created_at === "string" && typeof role.updated_at === "string"
    && (role.deleted_at === null || typeof role.deleted_at === "string");
}
