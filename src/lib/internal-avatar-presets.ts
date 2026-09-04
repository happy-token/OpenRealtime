import {
  readDigitalHumanAssetCatalog,
  type DigitalHumanAssetCatalog,
} from "./digital-human-asset-catalog";
import { INTERNAL_AVATAR_PRESET_IDS } from "./internal-avatar-ids";

export { INTERNAL_AVATAR_PRESET_IDS } from "./internal-avatar-ids";

const internalPresetIdSet = new Set<string>(INTERNAL_AVATAR_PRESET_IDS);

export function readInternalAvatarPresetCatalog(
  options: { includeLocal?: boolean } = {},
): DigitalHumanAssetCatalog {
  const catalog = readDigitalHumanAssetCatalog([], options);
  return {
    identities: catalog.identities
      .filter((identity) => internalPresetIdSet.has(identity.id)),
    motions: catalog.motions.filter((motion) => internalPresetIdSet.has(motion.visualIdentityId)),
  };
}
