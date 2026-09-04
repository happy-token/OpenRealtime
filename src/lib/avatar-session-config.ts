import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import type { OwnedAvatarRecord } from "./avatar-records";

export function avatarSessionConfig(
  avatar: OwnedAvatarRecord,
  base: AvatarDisplayConfig,
  requestedActionId?: string,
): AvatarDisplayConfig {
  const action = requestedActionId
    ? avatar.actions.find((candidate) => candidate.avatar_action_id === requestedActionId && !candidate.deleted_at)
    : null;
  if (!action && avatar.realtime_binding?.state === "accepted") {
    return {
      ...base,
      renderPath: "hosted",
      provider: "anam",
      avatarProfileId: avatar.realtime_binding.provider_avatar_id,
      hostedAvatarDisplayName: avatar.display_name,
      hostedAvatarImageUrl: avatar.source_image_url,
    };
  }
  return {
    ...base,
    renderPath: "segmented",
    segmentedPresetId: "custom-upload",
    segmentedAvatarId: avatar.avatar_id,
    segmentedDisplayName: avatar.display_name,
    segmentedAvatarActionId: action?.avatar_action_id ?? `builtin:identity-static:${avatar.avatar_id}`,
    segmentedLipSyncId: "wav2lip256",
  };
}

export function reconcileAvatarDisplayConfigWithOwnedAvatar(
  config: AvatarDisplayConfig,
  avatar: OwnedAvatarRecord,
  catalogActionIds: Iterable<string> = [],
): AvatarDisplayConfig {
  if (
    config.renderPath !== "segmented"
    || config.segmentedAvatarId !== avatar.avatar_id
    || avatar.deleted_at
  ) return config;

  const expectedImageActionId = `builtin:identity-static:${avatar.avatar_id}`;
  const selectedActionId = config.segmentedAvatarActionId;
  const selectedActionIsCurrent = avatar.actions.some((action) => (
    action.avatar_action_id === selectedActionId && !action.deleted_at
  )) || new Set(catalogActionIds).has(selectedActionId);
  const allRecordedActionsTrashed = avatar.actions.length > 0
    && avatar.actions.every((action) => Boolean(action.deleted_at));
  const selectedBuiltinIsValid = selectedActionId.startsWith("builtin:")
    && !selectedActionId.startsWith("builtin:identity-static:")
    && !allRecordedActionsTrashed;
  if (
    selectedActionId === expectedImageActionId
    || selectedActionIsCurrent
    || selectedBuiltinIsValid
  ) return config;

  return {
    ...config,
    segmentedPresetId: "custom-upload",
    segmentedAvatarId: avatar.avatar_id,
    segmentedDisplayName: avatar.display_name,
    segmentedAvatarActionId: expectedImageActionId,
  };
}
