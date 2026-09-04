import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import {
  resolveAvatarRendererBinding,
  resolveBuiltinAvatarSource,
} from "./avatar-renderer-preparation";

describe("avatar renderer preparation", () => {
  it("uses the realtime idle action as the default Shuchang segmented source", () => {
    expect(DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedAvatarActionId).toBe("builtin:shuchang-realtime-idle");

    const binding = resolveAvatarRendererBinding({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
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
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
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
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
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
