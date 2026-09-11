import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import type { AnamHostedAvatar } from "./anam-avatars";
import { fetchOwnedAvatar } from "./avatar-catalog-client";
import { avatarSessionConfig } from "./avatar-session-config";
import { readJsonResponse } from "./http-json-response";

export async function loadRequestedAvatarConfig(
  avatarId: string,
  base: AvatarDisplayConfig,
  signal: AbortSignal,
  actionId?: string,
): Promise<AvatarDisplayConfig> {
  if (avatarId.startsWith("anam-")) {
    const response = await fetch("/api/anam/avatars", { cache: "no-store", signal });
    const payload = await readJsonResponse<{ avatars?: AnamHostedAvatar[]; error?: string }>(response, "Anam 目录读取失败");
    if (!response.ok || !payload.avatars) throw new Error(payload.error || "Anam 目录读取失败");
    const avatar = payload.avatars.find((candidate) => `anam-${candidate.id}` === avatarId);
    if (!avatar) throw new Error("所选 Anam 形象不存在或当前 API Key 无权访问");
    return {
      ...base,
      renderPath: "hosted",
      provider: "anam",
      avatarProfileId: avatar.id,
      hostedAvatarDisplayName: avatar.displayName,
      hostedAvatarImageUrl: avatar.imageUrl,
    };
  }
  const avatar = await fetchOwnedAvatar(avatarId, signal);
  if (!avatar || avatar.deleted_at) throw new Error("所选 Avatar 不存在或已删除");
  return avatarSessionConfig(avatar, base, actionId);
}
