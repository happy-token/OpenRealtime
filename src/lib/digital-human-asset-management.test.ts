import { afterEach, describe, expect, it, vi } from "vitest";
import {
  hideMotionAsset,
  hideIdentityAsset,
  MOTION_ASSET_METADATA_STORAGE_KEY,
  readMotionAssetMetadata,
  storeMotionAssetDisplayName,
} from "./digital-human-asset-management";

afterEach(() => vi.unstubAllGlobals());

describe("digital human motion asset metadata", () => {
  it("stores unique editable names and locally removes an asset from the library", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    });

    expect(storeMotionAssetDisplayName("motion-1", "自然待机")).toBe("自然待机");
    expect(storeMotionAssetDisplayName("motion-2", "自然待机")).toBe("自然待机 2");
    expect(hideMotionAsset("motion-1")).toBe(true);
    expect(hideMotionAsset("motion-1")).toBe(false);
    expect(hideIdentityAsset("anchor")).toBe(true);
    expect(readMotionAssetMetadata()).toMatchObject({
      displayNames: { "motion-1": "自然待机", "motion-2": "自然待机 2" },
      hiddenIds: ["motion-1"],
      hiddenIdentityIds: ["anchor"],
    });
    expect(values.has(MOTION_ASSET_METADATA_STORAGE_KEY)).toBe(true);
  });
});
