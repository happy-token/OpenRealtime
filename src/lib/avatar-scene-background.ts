import type {
  AvatarDisplayConfig,
  ExperienceMode,
} from "@/components/digital-human/types";
import type { AvatarAsset } from "./avatar-catalog";
import { getBuiltinAvatarAction } from "./builtin-avatar-actions";
import { readDigitalHumanAssetCatalog } from "./digital-human-asset-catalog";

export type AvatarSceneBackground = {
  sceneKey: string;
  imageUrl: string | null;
  videoUrl: string | null;
};

export function shouldBypassAvatarSceneImageOptimization(imageUrl: string): boolean {
  return /^https?:\/\//i.test(imageUrl) || imageUrl.startsWith("/api/avatars/");
}

export function resolveMainScreenAvatarBackground(
  experienceMode: ExperienceMode,
  config: AvatarDisplayConfig,
  avatars: readonly AvatarAsset[],
): AvatarSceneBackground | null {
  return experienceMode === "avatar"
    ? resolveAvatarSceneBackground(config, avatars)
    : null;
}

export function resolveAvatarSceneBackground(
  config: AvatarDisplayConfig,
  avatars: readonly AvatarAsset[],
): AvatarSceneBackground {
  if (config.renderPath === "hosted") {
    return {
      sceneKey: `hosted:${config.provider}:${config.avatarProfileId}`,
      imageUrl: config.hostedAvatarImageUrl ?? null,
      videoUrl: null,
    };
  }

  const avatar = avatars.find((candidate) => candidate.avatarId === config.segmentedAvatarId);
  const action = avatar?.actions.find((candidate) => (
    candidate.avatarActionId === config.segmentedAvatarActionId
    && candidate.state === "available"
  ));
  const builtinAction = getBuiltinAvatarAction(config.segmentedAvatarActionId);
  const builtins = readDigitalHumanAssetCatalog([], { includeLocal: false });
  const curatedIdentity = builtins.identities.find((candidate) => candidate.id === config.segmentedAvatarId);
  const curatedMotion = builtins.motions.find((candidate) => (
    candidate.id === config.segmentedAvatarActionId
    && candidate.visualIdentityId === config.segmentedAvatarId
  ));

  return {
    sceneKey: `segmented:${config.segmentedAvatarId}:${config.segmentedAvatarActionId}`,
    imageUrl: avatar?.source.imageUrl ?? curatedIdentity?.previewImageUrl ?? builtinAction?.previewImageUrl ?? null,
    videoUrl: action?.videoUrl ?? curatedMotion?.videoUrl ?? builtinAction?.videoUrl ?? null,
  };
}
