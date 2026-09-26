import { expect, it } from "vitest";
import { buildTalkingMaterialCatalog, filterPairedMotionCatalog, resolveMotionPair, shouldShowTalkingMotion } from "./motion-orchestration";
import { DEFAULT_AVATAR_DISPLAY_CONFIG, parseAvatarDisplayConfig } from "./types";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
it("persists orchestration and only resolves a variant attached to the selected live source", () => {
  const config = parseAvatarDisplayConfig({ ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "orchestrated", segmentedAvatarId: "avatar-test", segmentedAvatarActionId: "action-test", motionTalkingVariantId: "talk-test" });
  expect(config.renderPath).toBe("orchestrated");
  const avatar = { avatar_id: "avatar-test", actions: [{ avatar_action_id: "action-test", video_url: "/idle.mp4", talking_variants: [{ id: "talk-test", source_video_url: "/idle.mp4", video_url: "/talk.mp4" }] }] } as OwnedAvatarRecord;
  expect(resolveMotionPair(avatar, config)).toEqual({ idle: "/idle.mp4", talking: "/talk.mp4" });
  expect(resolveMotionPair(avatar, { ...config, motionTalkingVariantId: "other" })).toBeNull();
  avatar.actions[0].talking_variants![0].deleted_at = "2026-09-20T00:00:00.000Z";
  expect(resolveMotionPair(avatar, config)).toBeNull();
  avatar.actions[0].talking_variants![0].deleted_at = null;
  avatar.actions[0].video_url = "/replaced.mp4";
  expect(resolveMotionPair(avatar, config)).toBeNull();
});

it("hides unpaired actions and avatars, including variants from an old source", () => {
  const owned = { avatar_id: "avatar-a", actions: [
    { avatar_action_id: "paired", video_url: "/idle", talking_variants: [{ source_video_url: "/idle", video_url: "/talk" }] },
    { avatar_action_id: "stale", video_url: "/new", talking_variants: [{ source_video_url: "/old", video_url: "/talk" }] },
  ] } as OwnedAvatarRecord;
  const asset = { avatarId: "avatar-a", actions: [
    { avatarActionId: "paired", videoUrl: "/idle", state: "available", pendingModelCount: 0 },
    { avatarActionId: "stale", videoUrl: "/new", state: "available", pendingModelCount: 0 },
  ] } as import("@/lib/avatar-catalog").AvatarAsset;
  expect(filterPairedMotionCatalog([asset], [owned])[0].actions.map(a => a.avatarActionId)).toEqual(["paired"]);
  expect(filterPairedMotionCatalog([{ ...asset, avatarId: "other" }], [owned])).toEqual([]);
});


it("lists each talking variant directly even when the base has pending lip models", () => {
  const owned = { avatar_id: "avatar-a", actions: [
    { avatar_action_id: "base", display_name: "柔和回应", video_url: "/idle", pending_model_count: 2, talking_variants: [
      { id: "muse", method: "musetalk", source_video_url: "/idle", video_url: "/muse" },
      { id: "lip", method: "lipforcing", source_video_url: "/idle", video_url: "/lip" },
      { id: "mini", method: "minimax", source_video_url: "/idle", video_url: "/mini" },
      { id: "trashed", method: "musetalk", source_video_url: "/idle", video_url: "/trashed", deleted_at: "today" },
      { id: "stale", method: "wav2lip", source_video_url: "/old", video_url: "/stale" },
    ] },
    { avatar_action_id: "deleted", deleted_at: "today", video_url: "/idle", talking_variants: [{ id: "gone", source_video_url: "/idle", video_url: "/gone" }] },
  ] } as unknown as OwnedAvatarRecord;
  const asset = { avatarId: "avatar-a", actions: [] } as unknown as import("@/lib/avatar-catalog").AvatarAsset;
  const material = buildTalkingMaterialCatalog([asset], [owned])[0];
  expect(material.actions.map(a => [a.avatarActionId, a.videoUrl])).toEqual([["muse", "/muse"], ["lip", "/lip"], ["mini", "/mini"]]);
  expect(material.actions.find(a => a.avatarActionId === "lip")?.displayName).toBe("柔和回应 · Lip Forcing");
  expect(material.actions.every(a => a.state === "available" && a.pendingModelCount === 0)).toBe(true);
  expect(buildTalkingMaterialCatalog([asset], [{ ...owned, deleted_at: "today" }])).toEqual([]);
});

it("shows the talking layer only during actual playback and drops it immediately on interruption", () => {
  expect(shouldShowTalkingMotion(true, true)).toBe(true);
  expect(shouldShowTalkingMotion(true, false)).toBe(false);
  expect(shouldShowTalkingMotion(false, true)).toBe(false);
  expect(shouldShowTalkingMotion(true, true, true)).toBe(false);
});
