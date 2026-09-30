import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import {
  resolveAvatarRendererBinding,
  resolveBuiltinAvatarSource,
} from "./avatar-renderer-preparation";

const legacyShuchangConfig = {
  ...DEFAULT_AVATAR_DISPLAY_CONFIG,
  segmentedAvatarId: "shuchang",
  segmentedDisplayName: "Shuchang",
  segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
};

describe("avatar renderer preparation", () => {
  it("prepares each curated built-in motion from packaged media", () => {
    for (const [avatarId, actionId, filename] of [
      ["avatar-8657be31-306e-428d-a013-7521e710ab6a", "338a867c-0661-4565-af6e-f0f2e0e9b3c7", "338a867c-0661-4565-af6e-f0f2e0e9b3c7.mp4"],
      ["avatar-qingzhao", "a30afa92-5213-428c-889b-0b0a4df05082", "a30afa92-5213-428c-889b-0b0a4df05082-recovered.mp4"],
      ["avatar-2843741c-815f-4117-b710-941802b0e2ab", "b3a35a5b-67aa-4f83-9d68-338a8bb2c581", "c4017965-045c-49bf-9a8a-41a13d4fdbce.mp4"],
    ]) {
      const binding = resolveAvatarRendererBinding({
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedAvatarId: avatarId,
        segmentedAvatarActionId: actionId,
      });
      expect(binding).not.toBeNull();
      expect(resolveBuiltinAvatarSource(binding!)).toBe(`public/digital-human/motion-bases/${filename}`);
    }
  });
  it("uses the realtime idle action as the default Shuchang segmented source", () => {
    expect(legacyShuchangConfig.segmentedAvatarActionId).toBe("builtin:shuchang-realtime-idle");

    const binding = resolveAvatarRendererBinding({
      ...legacyShuchangConfig,
      renderPath: "segmented",
    });

    expect(binding).toMatchObject({
      avatarId: "shuchang",
      avatarActionId: "builtin:shuchang-realtime-idle",
    });
    expect(resolveBuiltinAvatarSource(binding!)).toBe(
      "public/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
    );
  });

  it("keeps the existing Shuchang derivative compatible", () => {
    expect(resolveAvatarRendererBinding({
      ...legacyShuchangConfig,
      renderPath: "segmented",
      segmentedAvatarActionId: "builtin:liveportrait-optimized",
    })).toMatchObject({
      rendererAssetId: "shuchang256",
      avatarId: "shuchang",
      displayName: "Shuchang",
      modelId: "wav2lip256",
      providerModel: "wav2lip",
    });
  });

  it("binds the compatibility model to its own 96px assets", () => {
    expect(resolveAvatarRendererBinding({
      ...legacyShuchangConfig,
      renderPath: "segmented",
      segmentedLipSyncId: "wav2lip96",
      segmentedAvatarActionId: "builtin:liveportrait-optimized",
    })).toMatchObject({
      rendererAssetId: "shuchang",
      renderer: "livetalking-wav2lip96",
      modelId: "wav2lip96",
      modelSize: 96,
    });
  });

  it("creates a stable, safe binding for every OpenTalking motion asset", () => {
    const binding = resolveAvatarRendererBinding({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "ancient-beauty",
      segmentedDisplayName: "Shuchang",
      segmentedAvatarActionId: "builtin:opentalking:ancient-beauty",
    });

    expect(binding).toMatchObject({
      displayName: "古装美女",
      modelId: "wav2lip256",
      providerModel: "wav2lip",
    });
    expect(binding?.rendererAssetId).toMatch(/^[a-z0-9][a-z0-9_-]{0,63}$/);
    expect(resolveBuiltinAvatarSource(binding!)).toBe(
      "public/digital-human/opentalking/ancient-beauty/motion.mp4",
    );
  });

  it("keeps custom accepted motion assets eligible for preparation", () => {
    expect(resolveAvatarRendererBinding({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "identity-1",
      segmentedDisplayName: "Shuchang",
      segmentedAvatarActionId: "motion-base-1",
    })).toMatchObject({
      displayName: "identity-1",
      avatarActionId: "motion-base-1",
    });
  });

  it("resolves the Shuchang identity image as a static Wav2Lip source", () => {
    const binding = resolveAvatarRendererBinding({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "shuchang",
      segmentedAvatarActionId: "builtin:identity-static:shuchang",
    });

    expect(resolveBuiltinAvatarSource(binding!)).toBe(
      "public/digital-human/shuchang-preview.jpg",
    );
  });
});
