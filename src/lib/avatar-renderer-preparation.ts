import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import { getBuiltinAvatarAction } from "./builtin-avatar-actions";
import { OPENTALKING_AVATAR_CATALOG } from "./opentalking-avatar-catalog";
import builtinAvatarCatalog from "@/data/builtin-avatar-catalog.json";

export interface AvatarRendererBinding {
  renderer: "livetalking-wav2lip256" | "livetalking-wav2lip96";
  modelId: "wav2lip256" | "wav2lip96";
  modelSize: 256 | 96;
  providerModel: "wav2lip";
  rendererAssetId: string;
  displayName: string;
  avatarId: string;
  avatarActionId: string;
}

export function resolveAvatarRendererBinding(
  config: AvatarDisplayConfig,
): AvatarRendererBinding | null {
  if (config.renderPath !== "segmented"
    || config.segmentedAvatarId.startsWith("avatar-personal-")
    || (config.segmentedLipSyncId !== "wav2lip256" && config.segmentedLipSyncId !== "wav2lip96")) return null;
  const modelId = config.segmentedLipSyncId;
  const modelSize = modelId === "wav2lip256" ? 256 : 96;
  const avatarActionId = config.segmentedAvatarActionId
    || (config.segmentedVideoId === "liveportrait-optimized" ? "builtin:liveportrait-optimized" : "");
  if (!avatarActionId) return null;

  const packagedIdentity = OPENTALKING_AVATAR_CATALOG.find(
    (asset) => asset.id === config.segmentedAvatarId,
  );
  const isLegacyShuchang = config.segmentedAvatarId === "shuchang"
    && avatarActionId === "builtin:liveportrait-optimized";
  return {
    renderer: `livetalking-${modelId}`,
    modelId,
    modelSize,
    providerModel: "wav2lip",
    rendererAssetId: isLegacyShuchang
      ? modelSize === 256 ? "shuchang256" : "shuchang"
      : buildPreparedAvatarId(modelId, config.segmentedAvatarId, avatarActionId),
    displayName: config.segmentedDisplayName && (
      config.segmentedAvatarId === "shuchang" || config.segmentedDisplayName !== "Shuchang"
    )
      ? config.segmentedDisplayName
      : isLegacyShuchang ? "Shuchang" : packagedIdentity?.name ?? config.segmentedAvatarId,
    avatarId: config.segmentedAvatarId,
    avatarActionId,
  };
}

export function resolveBuiltinAvatarSource(binding: AvatarRendererBinding): string | null {
  const curated = builtinAvatarCatalog.find((avatar) => avatar.avatar_id === binding.avatarId)
    ?.actions.find((action) => action.avatar_action_id === binding.avatarActionId);
  if (curated?.video_url.startsWith("/digital-human/")) return `public${curated.video_url}`;
  const builtinAction = getBuiltinAvatarAction(binding.avatarActionId);
  if (builtinAction) return `public${builtinAction.videoUrl}`;
  if (binding.avatarActionId === "builtin:liveportrait-optimized") {
    return "public/digital-human/builtin-motion/liveportrait-optimized.mp4";
  }
  const match = /^builtin:opentalking:([a-z0-9-]+)$/.exec(binding.avatarActionId);
  if (match) {
    const asset = OPENTALKING_AVATAR_CATALOG.find(
      (candidate) => candidate.id === match[1] && candidate.motionVideoUrl,
    );
    return asset ? `public${asset.motionVideoUrl}` : null;
  }
  const staticMatch = /^builtin:identity-static:([a-z0-9-]+)$/.exec(binding.avatarActionId);
  if (!staticMatch) return null;
  if (staticMatch[1] === "shuchang") return "public/digital-human/shuchang-preview.jpg";
  const identity = OPENTALKING_AVATAR_CATALOG.find((candidate) => candidate.id === staticMatch[1]);
  return identity ? `public${identity.sourceImageUrl}` : null;
}

function buildPreparedAvatarId(
  modelId: AvatarRendererBinding["modelId"],
  avatarId: string,
  avatarActionId: string,
): string {
  const slug = avatarId.toLowerCase().replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 34) || "avatar";
  return `${modelId}-${slug}-${stableHash(`${avatarId}:${avatarActionId}`)}`;
}

function stableHash(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}
