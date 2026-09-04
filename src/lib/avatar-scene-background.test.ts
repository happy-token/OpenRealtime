import { describe, expect, it } from "vitest";
import type { AvatarAsset } from "./avatar-catalog";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import {
  resolveAvatarSceneBackground,
  resolveMainScreenAvatarBackground,
  shouldBypassAvatarSceneImageOptimization,
} from "./avatar-scene-background";

const avatar: AvatarAsset = {
  avatarId: "avatar-lin",
  displayName: "Lin",
  ownerId: "local-user",
  visibility: "private",
  source: { kind: "owned", imageUrl: "/api/avatars/avatar-lin/image" },
  actions: [{
    avatarActionId: "action-greeting",
    displayName: "挥手问候",
    state: "available",
    videoUrl: "/api/avatar-assets/artifacts/greeting",
    pendingModelCount: 0,
  }],
  realtimeBinding: null,
  canCreateActions: true,
  deletedAt: null,
};

describe("avatar scene background", () => {
  it("loads protected Avatar images directly so the browser session reaches the API", () => {
    expect(shouldBypassAvatarSceneImageOptimization("/api/avatars/avatar-lin/image")).toBe(true);
    expect(shouldBypassAvatarSceneImageOptimization("https://cdn.example.com/lin.jpg")).toBe(true);
    expect(shouldBypassAvatarSceneImageOptimization("/digital-human/shuchang-preview.jpg")).toBe(false);
  });

  it("does not invent an Avatar background when the main screen is in voice mode", () => {
    expect(resolveMainScreenAvatarBackground(
      "voice",
      {
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
      },
      [],
    )).toBeNull();
  });

  it("mirrors the main screen's selected segmented Avatar action", () => {
    const background = resolveAvatarSceneBackground({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "avatar-lin",
      segmentedDisplayName: "Lin",
      segmentedAvatarActionId: "action-greeting",
    }, [avatar]);

    expect(background).toEqual({
      sceneKey: "segmented:avatar-lin:action-greeting",
      imageUrl: "/api/avatars/avatar-lin/image",
      videoUrl: "/api/avatar-assets/artifacts/greeting",
    });
  });

  it("uses the packaged motion selected on the main screen", () => {
    const background = resolveAvatarSceneBackground({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
    }, []);

    expect(background).toMatchObject({
      sceneKey: "segmented:shuchang:builtin:shuchang-realtime-idle",
      imageUrl: "/digital-human/shuchang-preview.jpg",
      videoUrl: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
    });
  });

  it("mirrors a hosted Avatar with its main-screen preview image", () => {
    const background = resolveAvatarSceneBackground({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "hosted",
      avatarProfileId: "anam-lin",
      hostedAvatarDisplayName: "Lin Live",
      hostedAvatarImageUrl: "https://cdn.example.com/lin.jpg",
    }, []);

    expect(background).toEqual({
      sceneKey: "hosted:anam:anam-lin",
      imageUrl: "https://cdn.example.com/lin.jpg",
      videoUrl: null,
    });
  });

  it("keeps a static main-screen selection on the Avatar image", () => {
    const background = resolveAvatarSceneBackground({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "avatar-lin",
      segmentedDisplayName: "Lin",
      segmentedAvatarActionId: "builtin:identity-static:avatar-lin",
    }, [avatar]);

    expect(background).toMatchObject({
      imageUrl: "/api/avatars/avatar-lin/image",
      videoUrl: null,
    });
  });
});
