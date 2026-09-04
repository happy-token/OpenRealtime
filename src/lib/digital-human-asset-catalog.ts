import {
  readStoredAvatarIdentityDisplayName,
  readStoredCustomAvatarIdentities,
} from "./avatar-identity-sync";
import { readMotionAssetMetadata } from "./digital-human-asset-management";
import { avatarActionLabel, type AvatarActionAsset } from "./avatar-motion-catalog";
import {
  mergeWorkbenchIdentityAssets,
  type WorkbenchIdentityAsset,
} from "./digital-human-identity-catalog";
import { BUILTIN_AVATAR_ACTIONS } from "./builtin-avatar-actions";
import { OPENTALKING_AVATAR_CATALOG } from "./opentalking-avatar-catalog";

export type DigitalHumanMotionAsset = {
  id: string;
  visualIdentityId: string;
  name: string;
  previewImageUrl?: string;
  videoUrl: string;
  durationMs?: number;
  phase: "built-in" | AvatarActionAsset["phase"];
};

export type DigitalHumanAssetCatalog = {
  identities: WorkbenchIdentityAsset[];
  motions: DigitalHumanMotionAsset[];
};

const BUILT_IN_IDENTITIES: readonly WorkbenchIdentityAsset[] = [
  {
    id: "shuchang",
    name: "Shuchang",
    width: 512,
    height: 512,
    previewImageUrl: "/digital-human/shuchang-preview.jpg",
    sourceImageUrl: "/digital-human/shuchang-preview.jpg",
    origin: "当前资产",
    category: "saved",
  },
  ...OPENTALKING_AVATAR_CATALOG.map((asset) => ({
    ...asset,
    origin: "OpenTalking",
    category: "reference" as const,
  })),
];

const BUILT_IN_MOTIONS: readonly DigitalHumanMotionAsset[] = [
  ...BUILTIN_AVATAR_ACTIONS.map((action) => ({
    id: action.id,
    visualIdentityId: action.avatarId,
    name: action.name,
    previewImageUrl: action.previewImageUrl,
    videoUrl: action.videoUrl,
    phase: "built-in" as const,
  })),
  ...OPENTALKING_AVATAR_CATALOG
    .filter((asset) => asset.motionVideoUrl)
    .map((asset) => ({
      id: `builtin:opentalking:${asset.id}`,
      visualIdentityId: asset.id,
      name: `${asset.name} · 内置动作`,
      previewImageUrl: asset.previewImageUrl,
      videoUrl: asset.motionVideoUrl!,
      phase: "built-in" as const,
    })),
];

export function readDigitalHumanAssetCatalog(
  savedMotions: readonly AvatarActionAsset[] = [],
  options: { includeLocal?: boolean } = {},
): DigitalHumanAssetCatalog {
  const includeLocal = options.includeLocal ?? true;
  const metadata = includeLocal
    ? readMotionAssetMetadata()
    : { version: 1 as const, displayNames: {}, hiddenIds: [], hiddenIdentityIds: [] };
  const hiddenIdentityIds = new Set(metadata.hiddenIdentityIds);
  const hiddenMotionIds = new Set(metadata.hiddenIds);
  const identities = mergeWorkbenchIdentityAssets(
    BUILT_IN_IDENTITIES,
    includeLocal ? readStoredCustomAvatarIdentities() : [],
  )
    .filter((identity) => !hiddenIdentityIds.has(identity.id))
    .map((identity) => ({
      ...identity,
      name: includeLocal
        ? readStoredAvatarIdentityDisplayName(identity.id, identity.name)
        : identity.name,
    }));
  const motions = [
    ...BUILT_IN_MOTIONS,
    ...savedMotions.map<DigitalHumanMotionAsset>((motion) => ({
      id: motion.avatar_action_id,
      visualIdentityId: motion.avatar_id,
      name: avatarActionLabel(motion),
      videoUrl: `/api/avatar-assets/artifacts/${encodeURIComponent(motion.source_master_artifact_id)}`,
      durationMs: motion.source_media.duration_ms,
      phase: motion.phase,
    })),
  ]
    .filter((motion) => !hiddenMotionIds.has(motion.id))
    .map((motion) => ({
      ...motion,
      name: metadata.displayNames[motion.id] || motion.name,
    }));

  return { identities, motions };
}
