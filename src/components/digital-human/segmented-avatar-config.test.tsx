import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "./types";
import {
  activateMacLipSyncRuntime,
  AVATAR_IDENTITY_CHOICES,
  getLipSyncEffectPreview,
  LIP_SYNC_CHOICES,
  MAC_LIP_SYNC_RUNTIME_CHOICES,
  VIDEO_BASE_CHOICES,
  getPipelineCompatibility,
} from "./segmented-avatar-config";

describe("getLipSyncEffectPreview", () => {
  it("only exposes videos for exact tested avatar, motion-base, and lip-sync triples", () => {
    const testedTriples = new Set([
      "shuchang:liveportrait-optimized:dh-live-mini-v1",
      "shuchang:liveportrait-optimized:wav2lip256",
      "liteavatar-preset:avatar-bundled:liteavatar",
      "dh-live-preset:avatar-bundled:dh-live-mini-v1",
    ]);

    for (const avatar of AVATAR_IDENTITY_CHOICES) {
      for (const video of VIDEO_BASE_CHOICES) {
        for (const lipSync of LIP_SYNC_CHOICES) {
          const key = `${avatar.id}:${video.id}:${lipSync.id}`;
          const preview = getLipSyncEffectPreview(avatar.id, video.id, lipSync.id);
          expect(preview.kind, key).toBe(testedTriples.has(key) ? "video" : "pending");
        }
      }
    }
  });

  it("does not reuse Shuchang artifacts for a newly uploaded person", () => {
    expect(getLipSyncEffectPreview("custom-upload", "liveportrait-optimized", "dh-live-mini-v1")).toMatchObject({
      kind: "pending",
      title: "当前三段组合尚无 DH_live_mini 效果",
    });
    expect(getLipSyncEffectPreview("custom-upload", "liveportrait-optimized", "wav2lip256")).toMatchObject({
      kind: "pending",
      title: "当前三段组合尚无 Wav2Lip 256 效果",
    });
  });

  it("does not reuse a LivePortrait artifact after switching the action base", () => {
    expect(getLipSyncEffectPreview("shuchang", "ffmpeg-static", "dh-live-mini-v1").kind).toBe("pending");
    expect(getLipSyncEffectPreview("shuchang", "prepared-video", "wav2lip256").kind).toBe("pending");
  });

  it("blocks bundled motion assets for identities that do not own that preset", () => {
    expect(getPipelineCompatibility("shuchang", "avatar-bundled", "dh-live-mini-v1")).toMatchObject({
      kind: "blocked",
      title: "当前人物没有预置底片",
    });
    expect(getPipelineCompatibility("custom-upload", "avatar-bundled", "wav2lip256")).toMatchObject({
      kind: "blocked",
      title: "当前人物没有预置底片",
    });
  });

  it("only lists the verified local model without replacing the selected identity or motion", () => {
    expect(MAC_LIP_SYNC_RUNTIME_CHOICES).toEqual([
      { id: "wav2lip256", name: "Wav2Lip 256" },
      { id: "wav2lip96", name: "Wav2Lip 96" },
    ]);

    expect(activateMacLipSyncRuntime({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "companion",
      segmentedAvatarActionId: "builtin:opentalking:companion",
    }, "wav2lip256")).toMatchObject({
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "companion",
      segmentedAvatarActionId: "builtin:opentalking:companion",
      segmentedLipSyncId: "wav2lip256",
    });
  });
});
