import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OPENTALKING_AVATAR_CATALOG } from "./opentalking-avatar-catalog";

describe("OpenTalking built-in visual identity pack", () => {
  it("publishes every imported identity and its paired source video", () => {
    expect(OPENTALKING_AVATAR_CATALOG).toHaveLength(20);
    expect(OPENTALKING_AVATAR_CATALOG.filter((identity) => identity.motionVideoUrl)).toHaveLength(20);
    expect(OPENTALKING_AVATAR_CATALOG.map((identity) => identity.name)).toEqual(expect.arrayContaining([
      "主播",
      "古装美女",
      "视频通话",
      "新闻双人主播",
      "LivePortrait + MuseTalk",
      "职场女（动态）",
    ]));

    const ids = OPENTALKING_AVATAR_CATALOG.map((identity) => identity.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const identity of OPENTALKING_AVATAR_CATALOG) {
      expect(identity.previewImageUrl).toMatch(/^\/digital-human\/opentalking\/.+\/preview\.png$/);
      expect(identity.sourceImageUrl).toMatch(/^\/digital-human\/opentalking\/.+\/reference\.png$/);
      if (identity.motionVideoUrl) {
        expect(identity.motionVideoUrl).toMatch(/^\/digital-human\/opentalking\/.+\/motion\.mp4$/);
        expect(existsSync(join(process.cwd(), "public", identity.motionVideoUrl))).toBe(true);
      }
    }
  });
});
