import { describe, expect, it } from "vitest";
import {
  EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES,
  filterVisibleAvatarLibraryAssets,
  hideAvatarLibraryAsset,
  isAvatarLibraryAssetHidden,
  parseAvatarAssetLibraryPreferences,
  persistAvatarAssetLibraryPreferences,
  readAvatarAssetLibraryPreferences,
  resolveAvatarDisplayConfigAfterDeletion,
  restoreAvatarLibraryAssets,
} from "./avatar-asset-library-preferences";

describe("avatar asset library preferences", () => {
  it("removes a local identity from the visible asset library", () => {
    const next = hideAvatarLibraryAsset(
      EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES,
      "identity",
      "newscaster",
    );

    expect(isAvatarLibraryAssetHidden(next, "identity", "newscaster")).toBe(true);
    expect(isAvatarLibraryAssetHidden(next, "motion", "newscaster")).toBe(false);
  });

  it("restores valid hidden assets from persisted preferences", () => {
    expect(parseAvatarAssetLibraryPreferences(JSON.stringify({
      version: 1,
      hiddenIdentityIds: ["newscaster", "newscaster", "../unsafe"],
      hiddenMotionIds: ["opentalking:anchor", "motion-2026"],
    }))).toEqual({
      version: 1,
      hiddenIdentityIds: ["newscaster"],
      hiddenMotionIds: ["opentalking:anchor", "motion-2026"],
    });
  });

  it("restores every locally removed identity and motion", () => {
    expect(restoreAvatarLibraryAssets()).toEqual(EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES);
  });

  it("persists removed assets for the next configuration visit", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    const hidden = hideAvatarLibraryAsset(
      EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES,
      "motion",
      "opentalking:anchor",
    );

    persistAvatarAssetLibraryPreferences(hidden, storage);

    expect(readAvatarAssetLibraryPreferences(storage)).toEqual(hidden);
  });

  it("filters removed motions without hiding their source identity", () => {
    const preferences = hideAvatarLibraryAsset(
      EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES,
      "motion",
      "opentalking:anchor",
    );
    const assets = [{ id: "opentalking:anchor" }, { id: "opentalking:newscaster" }];

    expect(filterVisibleAvatarLibraryAssets(assets, preferences, "motion")).toEqual([
      { id: "opentalking:newscaster" },
    ]);
    expect(filterVisibleAvatarLibraryAssets(assets, preferences, "identity")).toEqual(assets);
  });

  it("falls back to the protected natural action when the current action is removed", () => {
    const current = {
      renderPath: "segmented" as const,
      provider: "anam" as const,
      avatarProfileId: "default-anam",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "anchor",
      segmentedVideoId: "liveportrait-optimized",
      segmentedAvatarActionId: "builtin:opentalking:anchor",
      segmentedLipSyncId: "dh-live-mini-v1",
      surface: "fullbleed" as const,
      framing: "half" as const,
      ratio: "16:9" as const,
      quality: "quality" as const,
      fallbackToClassic: true as const,
    };

    expect(resolveAvatarDisplayConfigAfterDeletion(current, {
      kind: "motion",
      id: "opentalking:anchor",
    })).toMatchObject({
      segmentedPresetId: "shuchang",
      segmentedAvatarId: "shuchang",
      segmentedVideoId: "liveportrait-optimized",
      segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
    });
  });
});
