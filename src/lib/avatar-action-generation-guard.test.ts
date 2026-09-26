import { describe, expect, it } from "vitest";
import { hasGeneratedAvatarAction } from "./avatar-action-generation-guard";

describe("avatar action generation guard", () => {
  const action = {
    avatar_action_id: "action-1",
    display_name: "甜美元气",
    video_url: "/media/action.mp4",
    pending_model_count: 0,
    created_at: "2026-09-24T00:00:00.000Z",
    deleted_at: null,
  };

  it("marks a named preset as generated when an active video exists", () => {
    expect(hasGeneratedAvatarAction([action], "甜美元气")).toBe(true);
  });

  it("ignores deleted actions and incomplete records", () => {
    expect(hasGeneratedAvatarAction([{ ...action, deleted_at: "2026-09-24T01:00:00.000Z" }], "甜美元气")).toBe(false);
    expect(hasGeneratedAvatarAction([{ ...action, video_url: null }], "甜美元气")).toBe(false);
  });

  it("normalizes surrounding whitespace but does not conflate different presets", () => {
    expect(hasGeneratedAvatarAction([{ ...action, display_name: " 甜美元气 " }], "甜美元气")).toBe(true);
    expect(hasGeneratedAvatarAction([action], "知性温柔")).toBe(false);
  });
});
