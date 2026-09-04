import { afterEach, describe, expect, it, vi } from "vitest";
import { AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, CUSTOM_AVATAR_IDENTITY_STORAGE_KEY } from "./avatar-identity-sync";
import { MOTION_ASSET_METADATA_STORAGE_KEY } from "./digital-human-asset-management";
import { readDigitalHumanAssetCatalog } from "./digital-human-asset-catalog";

afterEach(() => vi.unstubAllGlobals());

describe("digital human asset catalog", () => {
  it("projects the workbench identities, saved motions, names, and deletions through one catalog", () => {
    const customIdentityId = "custom-12345678-1234-4123-8123-123456789abc";
    const values = new Map<string, string>([
      [CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify({
        version: 2,
        selectedIdentityId: customIdentityId,
        identities: [{
          identityId: customIdentityId,
          name: "我的照片",
          dataUrl: "data:image/png;base64,photo",
          sourceSha256: "a".repeat(64),
          updatedAt: "2026-08-28T00:00:00.000Z",
        }],
      })],
      [AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, JSON.stringify({ companion: "小陪伴" })],
      [MOTION_ASSET_METADATA_STORAGE_KEY, JSON.stringify({
        version: 1,
        displayNames: {
          "builtin:opentalking:companion": "陪伴待机",
          "motion-saved-1": "我的问候动作",
        },
        hiddenIds: ["builtin:opentalking:anchor"],
        hiddenIdentityIds: ["anchor"],
      })],
    ]);
    vi.stubGlobal("window", {
      localStorage: { getItem: (key: string) => values.get(key) ?? null },
    });

    const catalog = readDigitalHumanAssetCatalog([{
      avatar_action_id: "motion-saved-1",
      avatar_id: customIdentityId,
      candidate_id: "candidate-1",
      phase: "ready",
      source_master_artifact_id: "artifact-1",
      source_media: { duration_ms: 2400, width: 720, height: 1280, video_codec: "h264", has_audio: false },
      renditions: [],
    }]);

    expect(catalog.identities.some((asset) => asset.id === "anchor")).toBe(false);
    expect(catalog.identities).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "companion", name: "小陪伴" }),
      expect.objectContaining({ id: customIdentityId, name: "我的照片", previewImageUrl: "data:image/png;base64,photo" }),
    ]));
    expect(catalog.motions.some((asset) => asset.id === "builtin:opentalking:anchor")).toBe(false);
    expect(catalog.motions).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "builtin:opentalking:companion", name: "陪伴待机" }),
      expect.objectContaining({ id: "motion-saved-1", name: "我的问候动作", videoUrl: "/api/avatar-assets/artifacts/artifact-1" }),
    ]));
  });
});
