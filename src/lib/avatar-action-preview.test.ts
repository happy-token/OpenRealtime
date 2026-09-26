import { describe, expect, it } from "vitest";
import { avatarActionPreviewSources } from "./avatar-action-preview";

describe("avatar action card preview sources", () => {
  it("falls back from an unavailable saved artifact to the matching built-in preview", () => {
    expect(avatarActionPreviewSources(
      "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      {
        display_name: "甜美元气",
        video_url: "/api/avatar-assets/artifacts/unavailable-action",
        talking_variants: [],
      },
    )).toEqual([
      "/api/avatar-assets/artifacts/unavailable-action",
      "/digital-human/liveportrait-actions/sweet-vitality.mp4",
    ]);
  });

  it("uses an active talking rendition when a custom action has no built-in preview", () => {
    expect(avatarActionPreviewSources(
      "avatar-custom",
      {
        display_name: "自定义动作",
        video_url: "/api/avatar-assets/artifacts/unavailable-custom-action",
        talking_variants: [{
          id: "talking-1",
          display_name: "自定义动作 · 讲话",
          method: "lipforcing",
          source_video_url: "/api/avatar-assets/artifacts/unavailable-custom-action",
          video_url: "/digital-human/talking-variants/custom-talking.mp4",
          processing: "original",
          validation: "pending",
          deleted_at: null,
        }],
      },
    )).toEqual([
      "/api/avatar-assets/artifacts/unavailable-custom-action",
      "/digital-human/talking-variants/custom-talking.mp4",
    ]);
  });
});
