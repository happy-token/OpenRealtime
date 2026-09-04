export const INTERNAL_AVATAR_PRESET_IDS = ["shuchang", "companion"] as const;

const internalAvatarPresetIdSet = new Set<string>(INTERNAL_AVATAR_PRESET_IDS);

export function isInternalAvatarPresetId(value: string) {
  return internalAvatarPresetIdSet.has(value);
}
