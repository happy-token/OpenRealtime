import { describe, expect, it } from "vitest";
import {
  createLivePortraitRetargetConfig,
  LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
  parseLivePortraitRetargetConfig,
} from "./liveportrait-retarget-config";

describe("LivePortrait retarget config", () => {
  it("creates the official single-image editor defaults", () => {
    expect(createLivePortraitRetargetConfig()).toEqual(LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG);
  });

  it("accepts supported pose and expression controls", () => {
    expect(parseLivePortraitRetargetConfig({
      ...LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
      head_yaw: 12,
      smile: 0.45,
      eye_open_delta: -0.1,
    })).toMatchObject({ head_yaw: 12, smile: 0.45, eye_open_delta: -0.1 });
  });

  it("rejects unknown and out-of-range controls", () => {
    expect(() => parseLivePortraitRetargetConfig({
      ...LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
      head_pitch: 16,
    })).toThrow("head_pitch");
    expect(() => parseLivePortraitRetargetConfig({
      ...LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
      lip_variation: 1,
    })).toThrow("未知字段");
  });
});
