import { describe, expect, it } from "vitest";
import {
  createLivePortraitMotionConfig,
  LIVEPORTRAIT_DEFAULT_MOTION_CONFIG,
  parseLivePortraitMotionConfig,
} from "./liveportrait-motion-config";

describe("LivePortrait offline motion config", () => {
  it("uses official offline defaults and keeps lip normalization off", () => {
    expect(createLivePortraitMotionConfig()).toEqual(LIVEPORTRAIT_DEFAULT_MOTION_CONFIG);
    expect(LIVEPORTRAIT_DEFAULT_MOTION_CONFIG.flag_normalize_lip).toBe(false);
  });

  it("maps user-facing strength to a bounded driving multiplier", () => {
    expect(createLivePortraitMotionConfig({ strength: "subtle" }).driving_multiplier).toBe(0.8);
    expect(createLivePortraitMotionConfig({ strength: "expressive" }).driving_multiplier).toBe(1.2);
  });

  it("accepts a continuous driving multiplier within the supported range", () => {
    expect(createLivePortraitMotionConfig({ drivingMultiplier: 1.07 }).driving_multiplier).toBe(1.07);
    expect(() => createLivePortraitMotionConfig({ drivingMultiplier: 1.51 })).toThrow("动作幅度必须在 0.5 到 1.5 之间");
  });

  it("rejects realtime OpenTalking fields", () => {
    expect(() => parseLivePortraitMotionConfig({
      ...LIVEPORTRAIT_DEFAULT_MOTION_CONFIG,
      cfg_scale: 4,
    })).toThrow("动作创建不支持参数 cfg_scale");
  });
});
