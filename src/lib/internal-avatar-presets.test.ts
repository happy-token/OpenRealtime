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
              hiddenIds: ["obsolete-motion"],
              hiddenIdentityIds: ["avatar-qingzhao"],
            })
          : null,
      },
    });

    const catalog = readInternalAvatarPresetCatalog();

    expect(catalog.identities.map((identity) => identity.id)).toEqual([
      "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      "avatar-2843741c-815f-4117-b710-941802b0e2ab",
    ]);
    expect(catalog.motions.map(motion => motion.visualIdentityId)).toEqual([
      "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      "avatar-qingzhao",
      "avatar-2843741c-815f-4117-b710-941802b0e2ab",
    ]);
    expect(catalog.identities.some((identity) => identity.id.startsWith("custom-"))).toBe(false);
  });
});
