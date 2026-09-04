import { afterEach, describe, expect, it, vi } from "vitest";
import { MOTION_ASSET_METADATA_STORAGE_KEY } from "./digital-human-asset-management";
import { readInternalAvatarPresetCatalog } from "./internal-avatar-presets";

afterEach(() => vi.unstubAllGlobals());

describe("internal Avatar presets", () => {
  it("applies locally deleted identities and actions without adding custom identities", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => key === MOTION_ASSET_METADATA_STORAGE_KEY
          ? JSON.stringify({
              version: 1,
              displayNames: {},
              hiddenIds: ["builtin:opentalking:shuchang"],
              hiddenIdentityIds: ["companion"],
            })
          : null,
      },
    });

    const catalog = readInternalAvatarPresetCatalog();

    expect(catalog.identities.map((identity) => identity.id)).toEqual(["shuchang"]);
    expect(catalog.motions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: "builtin:shuchang-realtime-idle",
        visualIdentityId: "shuchang",
        name: "实时待机",
        videoUrl: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
        phase: "built-in",
      }),
    ]));
    expect(catalog.motions.map((motion) => motion.id)).not.toContain("builtin:opentalking:shuchang");
    expect(catalog.identities.some((identity) => identity.id.startsWith("custom-"))).toBe(false);
  });
});
