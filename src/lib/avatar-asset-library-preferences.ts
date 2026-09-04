import type { AvatarDisplayConfig } from "@/components/digital-human/types";

export type AvatarLibraryAssetKind = "identity" | "motion";

export const AVATAR_ASSET_LIBRARY_PREFERENCES_STORAGE_KEY = "openrealtime-avatar-asset-library-preferences";

export type AvatarAssetLibraryPreferences = {
  version: 1;
  hiddenIdentityIds: string[];
  hiddenMotionIds: string[];
};

export const EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES: AvatarAssetLibraryPreferences = {
  version: 1,
  hiddenIdentityIds: [],
  hiddenMotionIds: [],
};

const ASSET_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export function parseAvatarAssetLibraryPreferences(raw: string | null): AvatarAssetLibraryPreferences {
  try {
    const value = JSON.parse(raw ?? "null") as Partial<AvatarAssetLibraryPreferences> | null;
    if (!value || value.version !== 1) return { ...EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES };
    return {
      version: 1,
      hiddenIdentityIds: validAssetIds(value.hiddenIdentityIds),
      hiddenMotionIds: validAssetIds(value.hiddenMotionIds),
    };
  } catch {
    return { ...EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES };
  }
}

export function hideAvatarLibraryAsset(
  preferences: AvatarAssetLibraryPreferences,
  kind: AvatarLibraryAssetKind,
  assetId: string,
): AvatarAssetLibraryPreferences {
  const key = kind === "identity" ? "hiddenIdentityIds" : "hiddenMotionIds";
  if (preferences[key].includes(assetId)) return preferences;
  return { ...preferences, [key]: [...preferences[key], assetId] };
}

export function isAvatarLibraryAssetHidden(
  preferences: AvatarAssetLibraryPreferences,
  kind: AvatarLibraryAssetKind,
  assetId: string,
) {
  const ids = kind === "identity" ? preferences.hiddenIdentityIds : preferences.hiddenMotionIds;
  return ids.includes(assetId);
}

export function restoreAvatarLibraryAssets(): AvatarAssetLibraryPreferences {
  return { version: 1, hiddenIdentityIds: [], hiddenMotionIds: [] };
}

export function filterVisibleAvatarLibraryAssets<T extends { id: string }>(
  assets: readonly T[],
  preferences: AvatarAssetLibraryPreferences,
  kind: AvatarLibraryAssetKind,
): T[] {
  return assets.filter((asset) => !isAvatarLibraryAssetHidden(preferences, kind, asset.id));
}

export function resolveAvatarDisplayConfigAfterDeletion(
  config: AvatarDisplayConfig,
  deletion: { kind: AvatarLibraryAssetKind; id: string },
): AvatarDisplayConfig {
  const removesSelectedMotion = deletion.kind === "motion" && (
    config.segmentedAvatarActionId === deletion.id
    || config.segmentedAvatarActionId === `builtin:${deletion.id}`
  );
  const removesSelectedIdentity = deletion.kind === "identity"
    && !config.segmentedAvatarActionId
    && config.segmentedAvatarId === deletion.id;
  if (!removesSelectedMotion && !removesSelectedIdentity) return config;
  return {
    ...config,
    segmentedPresetId: "shuchang",
    segmentedAvatarId: "shuchang",
    segmentedVideoId: "liveportrait-optimized",
    segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
  };
}

export function readAvatarAssetLibraryPreferences(
  storage: Pick<Storage, "getItem"> | undefined = typeof window === "undefined" ? undefined : window.localStorage,
): AvatarAssetLibraryPreferences {
  if (!storage) return { ...EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES };
  try {
    return parseAvatarAssetLibraryPreferences(storage.getItem(AVATAR_ASSET_LIBRARY_PREFERENCES_STORAGE_KEY));
  } catch {
    return { ...EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES };
  }
}

export function persistAvatarAssetLibraryPreferences(
  preferences: AvatarAssetLibraryPreferences,
  storage: Pick<Storage, "setItem"> | undefined = typeof window === "undefined" ? undefined : window.localStorage,
) {
  storage?.setItem(AVATAR_ASSET_LIBRARY_PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
}

function validAssetIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((id): id is string => (
    typeof id === "string" && ASSET_ID_PATTERN.test(id)
  )))];
}
