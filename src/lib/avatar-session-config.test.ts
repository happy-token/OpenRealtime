import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import type { OwnedAvatarRecord } from "./avatar-records";
import {
  avatarSessionConfig,
  reconcileAvatarDisplayConfigWithOwnedAvatar,
} from "./avatar-session-config";

const avatar: OwnedAvatarRecord = {
  avatar_id: "avatar-123",
  display_name: "Lin",
  source_image_url: "/lin.jpg",
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
  deleted_at: null,
  realtime_binding: null,
  actions: [],
};

describe("Avatar session config", () => {
  it("starts an image-only Avatar without requiring an action", () => {
    expect(avatarSessionConfig(avatar, DEFAULT_AVATAR_DISPLAY_CONFIG)).toMatchObject({
      renderPath: "segmented",
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "builtin:identity-static:avatar-123",
    });
  });

  it("uses an explicitly selected action", () => {
    expect(avatarSessionConfig({ ...avatar, actions: [{ avatar_action_id: "action-1", display_name: "待机", video_url: null, pending_model_count: 0, created_at: "", deleted_at: null }] }, DEFAULT_AVATAR_DISPLAY_CONFIG, "action-1")).toMatchObject({ segmentedAvatarActionId: "action-1" });
  });

  it("prefers an accepted realtime binding when no action is requested", () => {
    const config = avatarSessionConfig({ ...avatar, realtime_binding: { avatar_id: "avatar-123", provider: "anam", provider_avatar_id: "anam-1", avatar_model: "cara-4", state: "accepted" } }, DEFAULT_AVATAR_DISPLAY_CONFIG);
    expect(config).toMatchObject({ renderPath: "hosted", provider: "anam", avatarProfileId: "anam-1" });
  });

  it("falls back to the current source image when a persisted action was trashed", () => {
    const staleConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "avatar-123",
      segmentedDisplayName: "Lin",
      segmentedAvatarActionId: "action-old",
    };
    const replacedAvatar: OwnedAvatarRecord = {
      ...avatar,
      actions: [{
        avatar_action_id: "action-old",
        display_name: "旧动作",
        video_url: "/old.mp4",
        pending_model_count: 0,
        created_at: "2026-08-28T00:00:00Z",
        deleted_at: "2026-08-31T00:00:00Z",
      }],
    };

    expect(reconcileAvatarDisplayConfigWithOwnedAvatar(staleConfig, replacedAvatar)).toMatchObject({
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "builtin:identity-static:avatar-123",
    });
  });

  it("keeps a persisted action that is still active for the selected Avatar", () => {
    const activeConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "action-current",
    };
    const currentAvatar: OwnedAvatarRecord = {
      ...avatar,
      actions: [{
        avatar_action_id: "action-current",
        display_name: "当前动作",
        video_url: "/current.mp4",
        pending_model_count: 0,
        created_at: "2026-08-28T00:00:00Z",
        deleted_at: null,
      }],
    };

    expect(reconcileAvatarDisplayConfigWithOwnedAvatar(activeConfig, currentAvatar)).toBe(activeConfig);
  });

  it("keeps a persisted action supplied by the unified asset catalog", () => {
    const catalogConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "catalog-action",
    };

    expect(reconcileAvatarDisplayConfigWithOwnedAvatar(
      catalogConfig,
      avatar,
      ["catalog-action"],
    )).toBe(catalogConfig);
  });

  it("drops a built-in motion after all actions for the replaced source were trashed", () => {
    const staleBuiltinConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
    };
    const replacedAvatar: OwnedAvatarRecord = {
      ...avatar,
      actions: [{
        avatar_action_id: "action-old",
        display_name: "旧动作",
        video_url: "/old.mp4",
        pending_model_count: 0,
        created_at: "2026-08-28T00:00:00Z",
        deleted_at: "2026-08-31T00:00:00Z",
      }],
    };

    expect(reconcileAvatarDisplayConfigWithOwnedAvatar(staleBuiltinConfig, replacedAvatar)).toMatchObject({
      segmentedAvatarActionId: "builtin:identity-static:avatar-123",
    });
  });
});
