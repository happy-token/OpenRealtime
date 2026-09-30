import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG, parseAvatarDisplayConfig } from "./types";

describe("avatar display config", () => {
  it("defaults the segmented Shuchang pipeline to Wav2Lip 256", () => {
    expect(DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedLipSyncId).toBe("wav2lip256");
  });

  it("migrates the old Shuchang DH_live selection to the Wav2Lip runtime", () => {
    const parsed = parseAvatarDisplayConfig({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "shuchang",
      segmentedDisplayName: "Shuchang",
      segmentedLipSyncId: "dh-live-mini-v1",
    });

    expect(parsed.segmentedLipSyncId).toBe("wav2lip256");
  });

  it("preserves an explicit Wav2Lip 96 compatibility selection", () => {
    expect(parseAvatarDisplayConfig({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedLipSyncId: "wav2lip96",
    }).segmentedLipSyncId).toBe("wav2lip96");
  });

  it("keeps the explicit DH_live preset bound to its own model", () => {
    const parsed = parseAvatarDisplayConfig({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "dh-live-preset",
      segmentedAvatarId: "dh-live-preset",
      segmentedVideoId: "avatar-bundled",
      segmentedLipSyncId: "dh-live-mini-v1",
    });

    expect(parsed.segmentedLipSyncId).toBe("dh-live-mini-v1");
  });

  it("preserves the selected hosted avatar identity across page reloads", () => {
    const parsed = parseAvatarDisplayConfig({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      avatarProfileId: "anam-mia",
      hostedAvatarDisplayName: "Mia",
      hostedAvatarImageUrl: "https://newgxnc1uqs0jnqm.public.blob.vercel-storage.com/avatar-previews/mia.png",
    });

    expect(parsed.hostedAvatarDisplayName).toBe("Mia");
    expect(parsed.hostedAvatarImageUrl).toBe("https://newgxnc1uqs0jnqm.public.blob.vercel-storage.com/avatar-previews/mia.png");
  });

  it("does not retain an unsafe hosted avatar preview URL", () => {
    const parsed = parseAvatarDisplayConfig({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      avatarProfileId: "anam-mia",
      hostedAvatarDisplayName: "Mia",
      hostedAvatarImageUrl: "javascript:alert(1)",
    });

    expect(parsed.hostedAvatarImageUrl).toBeUndefined();
  });
});
