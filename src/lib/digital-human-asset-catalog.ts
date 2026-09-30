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
import { INTERNAL_AVATAR_PRESET_IDS } from "./internal-avatar-ids";

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
    id: INTERNAL_AVATAR_PRESET_IDS[0],
    name: "萨曼莎",
    previewImageUrl: "/digital-human/builtin-avatars/samantha.webp",
    sourceImageUrl: "/digital-human/builtin-avatars/samantha.webp",
    origin: "内置形象",
    category: "saved",
  },
  {
    id: INTERNAL_AVATAR_PRESET_IDS[1],
    name: "清照",
    previewImageUrl: "/digital-human/builtin-avatars/qingzhao.webp",
    sourceImageUrl: "/digital-human/builtin-avatars/qingzhao.webp",
    origin: "内置形象",
    category: "saved",
  },
  {
    id: INTERNAL_AVATAR_PRESET_IDS[2],
    name: "若水",
    previewImageUrl: "/digital-human/builtin-avatars/ruoshui.webp",
    sourceImageUrl: "/digital-human/builtin-avatars/ruoshui.webp",
    origin: "内置形象",
    category: "saved",
  },
];

// Initial previews for the curated identities; the managed records supply the full action and talking catalog.
const BUILT_IN_MOTIONS: readonly DigitalHumanMotionAsset[] = [
  { id: "338a867c-0661-4565-af6e-f0f2e0e9b3c7", visualIdentityId: INTERNAL_AVATAR_PRESET_IDS[0], name: "侧头微笑", videoUrl: "/digital-human/motion-bases/338a867c-0661-4565-af6e-f0f2e0e9b3c7.mp4", phase: "built-in" },
  { id: "a30afa92-5213-428c-889b-0b0a4df05082", visualIdentityId: INTERNAL_AVATAR_PRESET_IDS[1], name: "冷艳夜色", videoUrl: "/digital-human/motion-bases/a30afa92-5213-428c-889b-0b0a4df05082-recovered.mp4", phase: "built-in" },
  { id: "b3a35a5b-67aa-4f83-9d68-338a8bb2c581", visualIdentityId: INTERNAL_AVATAR_PRESET_IDS[2], name: "甜美元气", videoUrl: "/digital-human/motion-bases/c4017965-045c-49bf-9a8a-41a13d4fdbce.mp4", phase: "built-in" },
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
