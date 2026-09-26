import type { OwnedAvatarActionRecord } from "./avatar-records";
import { readJsonResponse } from "./http-json-response";

export async function saveGeneratedPersonalAction({
  taskId,
  avatarId,
}: {
  taskId: string;
  avatarId: string;
}): Promise<OwnedAvatarActionRecord> {
  const assetResponse = await fetch("/api/user/motion-assets", jsonRequest({ taskId }));
  const assetPayload = await readJsonResponse<{ asset?: { id: string }; error?: string }>(assetResponse, "动作素材保存失败");
  if (!assetResponse.ok || !assetPayload.asset?.id) {
    throw new Error(assetPayload.error || "动作素材保存失败");
  }

  const actionResponse = await fetch(
    `/api/user/avatars/${encodeURIComponent(avatarId)}/actions`,
    jsonRequest({ motionId: assetPayload.asset.id }),
  );
  const actionPayload = await readJsonResponse<{ action?: OwnedAvatarActionRecord; error?: string }>(actionResponse, "动作关联失败");
  if (!actionResponse.ok || !actionPayload.action) {
    throw new Error(actionPayload.error || "动作关联失败");
  }
  return actionPayload.action;
}

function jsonRequest(body: object): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
