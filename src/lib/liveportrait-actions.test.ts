import { access } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LIVEPORTRAIT_ACTIONS } from "./liveportrait-actions";

describe("LivePortrait built-in action references", () => {
  it("publishes the approved references with stable user-facing names", () => {
    expect(LIVEPORTRAIT_ACTIONS.map(({ id, name, referenceVideoUrl }) => ({ id, name, referenceVideoUrl }))).toEqual([
      { id: "sweet-vitality", name: "甜美元气", referenceVideoUrl: "/digital-human/liveportrait-actions/sweet-vitality.mp4" },
      { id: "soft-glow", name: "纯欲柔光", referenceVideoUrl: "/digital-human/liveportrait-actions/soft-glow.mp4" },
      { id: "cool-night", name: "冷艳夜色", referenceVideoUrl: "/digital-human/liveportrait-actions/cool-night.mp4" },
      { id: "gentle-intellectual", name: "知性温柔", referenceVideoUrl: "/digital-human/liveportrait-actions/gentle-intellectual.mp4" },
      { id: "melancholy-empathy", name: "忧郁共鸣", referenceVideoUrl: "/digital-human/liveportrait-actions/melancholy-empathy.mp4" },
    ]);
  });

  it("keeps every browser preview backed by the same copied project asset used for rendering", async () => {
    await Promise.all(LIVEPORTRAIT_ACTIONS.map(async (action) => {
      expect(action.source).toEqual({
        scope: "project",
        relativePath: `public${action.referenceVideoUrl}`,
      });

    }));
  });

  it.runIf(process.env.RUN_LOCAL_MEDIA === "1")("finds every installed local media file", async () => {
    await Promise.all(LIVEPORTRAIT_ACTIONS.map((action) => access(path.join(process.cwd(), action.source.relativePath))));
  });

  it("treats every confirmed built-in reference as ready to generate and save", () => {
    expect(LIVEPORTRAIT_ACTIONS.filter((action) => !action.closedMouthSafe).map((action) => action.id)).toEqual([]);
    expect(LIVEPORTRAIT_ACTIONS.filter((action) => action.caution).map((action) => action.id)).toEqual([]);
  });
});
