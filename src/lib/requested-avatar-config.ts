import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import type { AnamHostedAvatar } from "./anam-avatars";
import { fetchOwnedAvatar } from "./avatar-catalog-client";
import { avatarSessionConfig } from "./avatar-session-config";
import { readJsonResponse } from "./http-json-response";
import type { RolePresentationMode } from "./role-records";

export async function loadRequestedAvatarConfig(
  avatarId: string,
  base: AvatarDisplayConfig,
  signal: AbortSignal,
  actionId?: string,
  roleMode?: RolePresentationMode,
  talkingVariantId?: string,
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
  if (roleMode === "realtime") return avatarSessionConfig(avatar, base);

  const availableActions = avatar.actions.filter((action) => !action.deleted_at && action.video_url);
  const requestedAction = avatar.actions.find((action) => action.avatar_action_id === actionId && !action.deleted_at);
  const offlineActions = availableActions.filter((candidate) => candidate.talking_variants?.some((variant) =>
    variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === candidate.video_url));
  const action = roleMode === "offline"
    ? offlineActions.find((candidate) => candidate.avatar_action_id === actionId) ?? offlineActions[0]
    : requestedAction ?? availableActions[0];
  const config = avatarSessionConfig(avatar, base, action?.avatar_action_id);
  if (roleMode !== "offline") return config;

  const availableVariants = action?.talking_variants?.filter((candidate) => (
    candidate.method === "lipforcing" && !candidate.deleted_at && candidate.video_url && candidate.source_video_url === action.video_url
  )) ?? [];
  const variant = availableVariants.find((candidate) => candidate.id === talkingVariantId) ?? availableVariants[0];
  if (!variant) throw new Error("所选角色还没有可用的口型对齐");
  return { ...config, renderPath: "orchestrated", motionTalkingVariantId: variant.id };
}
