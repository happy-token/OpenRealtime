import type { AvatarRealtimeBindingRecord } from "./avatar-catalog";
import type { OwnedAvatarActionRecord, OwnedAvatarRecord } from "./avatar-records";
import { readJsonResponse } from "./http-json-response";

export async function fetchOwnedAvatars(signal?: AbortSignal) {
  const response = await fetch("/api/avatars", { cache: "no-store", signal });
  const payload = await readJsonResponse<{ avatars?: OwnedAvatarRecord[]; error?: string }>(response, "Avatar 目录读取失败");
  if (!response.ok || !payload.avatars) throw new Error(payload.error || "Avatar 目录读取失败");
  return payload.avatars;
}

export async function fetchPersonalAvatars(signal?: AbortSignal) {
  const response = await fetch("/api/user/avatars", { cache: "no-store", signal });
  if (response.status === 401) return [];
  const payload = await readJsonResponse<{ avatars?: OwnedAvatarRecord[]; error?: string }>(response, "个人数字人目录读取失败");
  if (!response.ok || !payload.avatars) throw new Error(payload.error || "个人数字人目录读取失败");
  return payload.avatars;
}

export async function fetchOwnedAvatar(avatarId: string, signal?: AbortSignal) {
  const endpoint = avatarId.startsWith("avatar-personal-") ? "/api/user/avatars" : "/api/avatars";
  const response = await fetch(`${endpoint}/${encodeURIComponent(avatarId)}`, { cache: "no-store", signal });
  const payload = await readJsonResponse<{ avatar?: OwnedAvatarRecord; error?: string }>(response, "Avatar 读取失败");
  if (response.status === 404) return null;
  if (!response.ok || !payload.avatar) throw new Error(payload.error || "Avatar 读取失败");
  return payload.avatar;
}

export async function setOwnedAvatarTalkingVariantDeletion(
  avatarId: string,
  avatarActionId: string,
  variantId: string,
  deleted: boolean,
): Promise<OwnedAvatarActionRecord> {
  const url = `${avatarApiRoot(avatarId)}/${encodeURIComponent(avatarId)}/actions/${encodeURIComponent(avatarActionId)}/talking-variants/${encodeURIComponent(variantId)}`;
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation: deleted ? "trash" : "restore" }),
  });
  const payload = await readJsonResponse<{ action?: OwnedAvatarActionRecord; error?: string }>(response, "口型对齐更新失败");
  if (!response.ok || !payload.action) throw new Error(payload.error || "口型对齐更新失败");
  return payload.action;
}

export async function renameOwnedAvatarTalkingVariant(
  avatarId: string,
  avatarActionId: string,
  variantId: string,
  displayName: string,
): Promise<OwnedAvatarActionRecord> {
  const url = `${avatarApiRoot(avatarId)}/${encodeURIComponent(avatarId)}/actions/${encodeURIComponent(avatarActionId)}/talking-variants/${encodeURIComponent(variantId)}`;
  const response = await fetch(url, jsonRequest("PATCH", { operation: "rename", displayName }));
  const payload = await readJsonResponse<{ action?: OwnedAvatarActionRecord; error?: string }>(response, "口型对齐改名失败");
  if (!response.ok || !payload.action) throw new Error(payload.error || "口型对齐改名失败");
  return payload.action;
}

export async function createOwnedAvatar(input: { displayName: string; sourceImageDataUrl: string; avatarId?: string }) {
  return avatarMutation("/api/avatars", { method: "POST", body: JSON.stringify(input) });
}

export async function setOwnedAvatarDeletion(avatarId: string, deleted: boolean) {
  return avatarMutation(`/api/avatars/${encodeURIComponent(avatarId)}`, {
    method: "PATCH",
    body: JSON.stringify({ operation: deleted ? "trash" : "restore" }),
  });
}

export async function renameOwnedAvatar(avatarId: string, displayName: string) {
  return avatarMutation(`${avatarApiRoot(avatarId)}/${encodeURIComponent(avatarId)}`, {
    method: "PATCH",
    body: JSON.stringify({ operation: "rename", displayName }),
  });
}

export async function acceptOwnedAvatarRealtimeBinding(
  avatarId: string,
  binding: Pick<AvatarRealtimeBindingRecord, "provider_avatar_id" | "avatar_model" | "preview_video_url">,
) {
  return avatarMutation(`/api/avatars/${encodeURIComponent(avatarId)}`, {
    method: "PATCH",
    body: JSON.stringify({ operation: "acceptRealtimeBinding", binding }),
  });
}

export async function replaceOwnedAvatarSourceImage(
  avatarId: string,
  input: { sourceImageDataUrl: string; trashActions: boolean },
) {
  return avatarMutation(`/api/avatars/${encodeURIComponent(avatarId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      operation: "replaceSourceImage",
      sourceImageDataUrl: input.sourceImageDataUrl,
      trashActions: input.trashActions,
    }),
  });
}

export async function appendOwnedAvatarAction(
  avatarId: string,
  action: Pick<OwnedAvatarActionRecord, "avatar_action_id" | "display_name" | "video_url"> & { pending_model_count?: number },
) {
  const response = await fetch(`/api/avatars/${encodeURIComponent(avatarId)}/actions`, jsonRequest("POST", action));
  const payload = await readJsonResponse<{ action?: OwnedAvatarActionRecord; error?: string }>(response, "Avatar 动作保存失败");
  if (!response.ok || !payload.action) throw new Error(payload.error || "Avatar 动作保存失败");
  return payload.action;
}

export async function updateOwnedAvatarAction(
  avatarId: string,
  avatarActionId: string,
  input:
    | { operation: "trash" | "restore" }
    | { operation: "preparation"; pendingModelCount: number }
    | { operation: "rename"; displayName: string },
) {
  const response = await fetch(
    `${avatarApiRoot(avatarId)}/${encodeURIComponent(avatarId)}/actions/${encodeURIComponent(avatarActionId)}`,
    jsonRequest("PATCH", input),
  );
  const payload = await readJsonResponse<{ action?: OwnedAvatarActionRecord; error?: string }>(response, "Avatar 动作更新失败");
  if (!response.ok || !payload.action) throw new Error(payload.error || "Avatar 动作更新失败");
  return payload.action;
}

export function avatarApiRoot(avatarId: string) {
  return avatarId.startsWith("avatar-personal-") ? "/api/user/avatars" : "/api/avatars";
}

async function avatarMutation(path: string, init: RequestInit) {
  const response = await fetch(path, { ...jsonRequest(init.method || "POST", undefined), ...init });
  const payload = await readJsonResponse<{ avatar?: OwnedAvatarRecord; error?: string }>(response, "Avatar 保存失败");
  if (!response.ok || !payload.avatar) throw new Error(payload.error || "Avatar 保存失败");
  return payload.avatar;
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}
