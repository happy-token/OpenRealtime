import { readJsonResponse } from "./http-json-response";
import type { RoleDefaultSelections, RoleRecord, RolePresentationMode, RoleVoiceDialect } from "./role-records";

export class RoleCreationError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function fetchRoles(signal?: AbortSignal) {
  const [personal, shared] = await Promise.all([
    fetchRoleList("/api/user/roles", signal),
    fetchRoleList("/api/roles", signal),
  ]);
  return [...personal, ...shared];
}

async function fetchRoleList(url: string, signal?: AbortSignal) {
  const response = await fetch(url, { cache: "no-store", signal });
  if (response.status === 401 || response.status === 403) return [];
  const payload = await readJsonResponse<{ roles?: RoleRecord[]; error?: string }>(response, "角色列表读取失败");
  if (!response.ok || !payload.roles) throw new Error(payload.error || "角色列表读取失败");
  return payload.roles;
}

export async function fetchRole(roleId: string, signal?: AbortSignal) {
  const endpoint = roleId.startsWith("role-personal-") ? "/api/user/roles" : "/api/roles";
  const response = await fetch(`${endpoint}/${encodeURIComponent(roleId)}`, { cache: "no-store", signal });
  const payload = await readJsonResponse<{ role?: RoleRecord; error?: string }>(response, "角色读取失败");
  if (response.status === 404) return null;
  if (!response.ok || !payload.role) throw new Error(payload.error || "角色读取失败");
  return payload.role;
}

export async function createRole(input: {
  displayName: string;
  voiceProvider: "bailian" | "doubao";
  voiceId: string;
  voiceDialect?: RoleVoiceDialect;
  asrProvider?: RoleRecord["asr_provider"];
  llmProvider?: RoleRecord["llm_provider"];
  personaId: string | null;
  avatarId: string | null;
  enabledModes: RolePresentationMode[];
  defaultMode: RolePresentationMode;
  defaultSelections?: RoleDefaultSelections;
  memoryEnabled: boolean;
  modelId?: string | null;
  toolIds: string[];
}) {
  const init: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  };
  let response = await fetch("/api/user/roles", init);
  if (response.status === 401) {
    // Shared creation remains protected by the server's admin/local-test authorization.
    response = await fetch("/api/roles", init);
    if (response.status === 401 || response.status === 403) {
      throw new RoleCreationError("请先登录后创建角色", 401);
    }
  }
  const payload = await readJsonResponse<{ role?: RoleRecord; error?: string }>(response, "角色创建失败");
  if (!response.ok || !payload.role) throw new RoleCreationError(payload.error || "角色创建失败", response.status);
  return payload.role;
}

export async function saveRole(roleId: string, input: {
  displayName: string;
  voiceProvider: "bailian" | "doubao";
  voiceId: string;
  voiceDialect?: RoleVoiceDialect;
  asrProvider?: RoleRecord["asr_provider"];
  llmProvider?: RoleRecord["llm_provider"];
  personaId: string | null;
  avatarId: string | null;
  enabledModes: RolePresentationMode[];
  defaultMode: RolePresentationMode;
  defaultSelections?: RoleDefaultSelections;
  memoryEnabled: boolean;
  modelId?: string | null;
  toolIds: string[];
}) {
  const endpoint = roleId.startsWith("role-personal-") ? "/api/user/roles" : "/api/roles";
  const response = await fetch(`${endpoint}/${encodeURIComponent(roleId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const payload = await readJsonResponse<{ role?: RoleRecord; error?: string }>(response, "角色保存失败");
  if (!response.ok || !payload.role) throw new Error(payload.error || "角色保存失败");
  return payload.role;
}

export async function deleteRole(roleId: string) {
  const endpoint = roleId.startsWith("role-personal-") ? "/api/user/roles" : "/api/roles";
  const response = await fetch(`${endpoint}/${encodeURIComponent(roleId)}`, { method: "DELETE" });
  const payload = await readJsonResponse<{ deleted?: boolean; error?: string }>(response, "角色删除失败");
  if (!response.ok || !payload.deleted) throw new Error(payload.error || "角色删除失败");
  return true;
}
