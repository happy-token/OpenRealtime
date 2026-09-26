import { describe, expect, it } from "vitest";
import type { OwnedAvatarRecord } from "./avatar-records";
import { enabledRoleModesForAvatar, isRoleDefaultSelections, isRoleRecordId, preferredRoleMode, resolveRoleDefaultSelection, roleModesForAvatar } from "./role-records";

function avatar(overrides: Partial<OwnedAvatarRecord> = {}): OwnedAvatarRecord {
  return {
    avatar_id: "avatar-test",
    display_name: "测试形象",
    source_image_url: "/avatar.png",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    deleted_at: null,
    realtime_binding: null,
    actions: [],
    ...overrides,
  };
}

describe("role presentation modes", () => {
  it("accepts built-in and catalog role IDs for safe return navigation", () => {
    expect(isRoleRecordId("default-assistant")).toBe(true);
    expect(isRoleRecordId("role-personal-123")).toBe(true);
    expect(isRoleRecordId("../roles/admin")).toBe(false);
  });
  it("prefers a ready offline mode and resolves a removed default material", () => {
    const ready = avatar({ actions: [{
      avatar_action_id: "action-ready", display_name: "站立", video_url: "/idle.mp4",
      pending_model_count: 0, created_at: "2026-01-01T00:00:00.000Z", deleted_at: null,
      talking_variants: [{ id: "talk-ready", display_name: "讲话", method: "lipforcing", source_video_url: "/idle.mp4",
        video_url: "/talk.mp4", processing: "mouth-only", validation: "pending" }],
    }], realtime_binding: { provider_avatar_id: "anam-avatar", avatar_id: "avatar-test", provider: "anam", avatar_model: "model-1", state: "accepted" } });
    expect(preferredRoleMode(roleModesForAvatar(ready))).toBe("offline");
    expect(resolveRoleDefaultSelection(ready, "offline", { action_id: "action-deleted", talking_variant_id: "talk-deleted" }))
      .toEqual({ action_id: "action-ready", talking_variant_id: "talk-ready" });
    expect(isRoleDefaultSelections({ offline: { action_id: "action-ready", talking_variant_id: "talk-ready" } })).toBe(true);
    expect(isRoleDefaultSelections({ offline: { action_id: "../invalid" } })).toBe(false);
  });
  it("keeps a role conversation-only without an avatar", () => {
    expect(roleModesForAvatar(null)).toEqual(["conversation"]);
  });

  it("enables lip sync when an avatar has an action video", () => {
    expect(roleModesForAvatar(avatar({
      actions: [{
        avatar_action_id: "action-idle",
        display_name: "待机",
        video_url: "/idle.mp4",
        pending_model_count: 0,
        created_at: "2026-01-01T00:00:00.000Z",
        deleted_at: null,
      }],
    }))).toEqual(["conversation", "lip-sync"]);
  });

  it("enables offline playback when an action has a talking variant", () => {
    expect(roleModesForAvatar(avatar({
      actions: [{
        avatar_action_id: "action-talk",
        display_name: "讲话",
        video_url: "/talk.mp4",
        pending_model_count: 0,
        created_at: "2026-01-01T00:00:00.000Z",
        deleted_at: null,
        talking_variants: [{
          id: "variant-1",
          display_name: "口型对齐",
          method: "lipforcing",
          source_video_url: "/talk.mp4",
          video_url: "/talking.mp4",
          processing: "mouth-only",
          validation: "pending",
        }],
      }],
    }))).toEqual(["conversation", "offline", "lip-sync"]);
  });

  it("unlocks personal offline modes only after a Lip Forcing variant is saved", () => {
    const personal = avatar({ avatar_id: "avatar-personal-123", actions: [{
      avatar_action_id: "motion-123", display_name: "站立", video_url: "/api/user/motion-assets/123?preview=1",
      pending_model_count: 0, created_at: "2026-01-01T00:00:00.000Z", deleted_at: null,
    }] });
    expect(roleModesForAvatar(personal)).toEqual(["conversation", "lip-sync"]);
    personal.actions[0].talking_variants = [{
      id: "lipforcing-123", display_name: "讲话", method: "lipforcing", source_video_url: personal.actions[0].video_url!,
      video_url: "/api/user/avatars/avatar-personal-123/actions/motion-123/talking-variants/lipforcing-123/video",
      processing: "original", validation: "pending",
    }];
    expect(roleModesForAvatar(personal)).toEqual(["conversation", "offline", "lip-sync"]);
  });

  it("only enables realtime for an accepted Anam binding", () => {
    const pending = avatar({ realtime_binding: {
      provider_avatar_id: "anam-avatar",
      avatar_id: "avatar-test",
      provider: "anam",
      avatar_model: "model-1",
      state: "awaiting-acceptance",
    } });
    expect(roleModesForAvatar(pending)).toEqual(["conversation"]);

    const accepted = avatar({ realtime_binding: { ...pending.realtime_binding!, state: "accepted" } });
    expect(roleModesForAvatar(accepted)).toEqual(["conversation", "realtime"]);
    expect(preferredRoleMode(roleModesForAvatar(accepted))).toBe("realtime");
  });

  it("keeps only the requested modes that the selected avatar can support", () => {
    const ready = avatar({ actions: [{
      avatar_action_id: "action-ready", display_name: "站立", video_url: "/idle.mp4",
      pending_model_count: 0, created_at: "2026-01-01T00:00:00.000Z", deleted_at: null,
      talking_variants: [{ id: "talk-ready", display_name: "讲话", method: "lipforcing", source_video_url: "/idle.mp4",
        video_url: "/talk.mp4", processing: "mouth-only", validation: "pending" }],
    }] });
    expect(enabledRoleModesForAvatar(["conversation", "lip-sync"], ready)).toEqual(["conversation", "lip-sync"]);
    expect(enabledRoleModesForAvatar(["realtime"], ready)).toEqual(["conversation"]);
    expect(enabledRoleModesForAvatar(["offline"], ready)).toEqual(["offline"]);
  });
});
