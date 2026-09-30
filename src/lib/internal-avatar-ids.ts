export const INTERNAL_AVATAR_PRESET_IDS = [
  "avatar-8657be31-306e-428d-a013-7521e710ab6a", // 萨曼莎
  "avatar-qingzhao", // 清照
  "avatar-2843741c-815f-4117-b710-941802b0e2ab", // 若水
] as const;

const internalAvatarPresetIdSet = new Set<string>(INTERNAL_AVATAR_PRESET_IDS);

export function isInternalAvatarPresetId(value: string) {
  return internalAvatarPresetIdSet.has(value);
}
