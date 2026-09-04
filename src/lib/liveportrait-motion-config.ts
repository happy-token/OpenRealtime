export const LIVEPORTRAIT_ANIMATION_REGIONS = ["all", "exp", "pose", "eyes"] as const;

export type LivePortraitAnimationRegion = (typeof LIVEPORTRAIT_ANIMATION_REGIONS)[number];
export type LivePortraitMotionStrength = "subtle" | "natural" | "expressive";

export type LivePortraitMotionConfig = {
  animation_region: LivePortraitAnimationRegion;
  driving_multiplier: number;
  flag_stitching: boolean;
  flag_pasteback: boolean;
  flag_normalize_lip: boolean;
  flag_relative_motion: boolean;
};

export const LIVEPORTRAIT_DEFAULT_MOTION_CONFIG: LivePortraitMotionConfig = {
  animation_region: "all",
  driving_multiplier: 1,
  flag_stitching: true,
  flag_pasteback: true,
  flag_normalize_lip: false,
  flag_relative_motion: true,
};

export const LIVEPORTRAIT_STRENGTH_MULTIPLIERS = {
  subtle: 0.8,
  natural: 1,
  expressive: 1.2,
} as const satisfies Record<LivePortraitMotionStrength, number>;

export function createLivePortraitMotionConfig({
  animationRegion = "all",
  strength = "natural",
  drivingMultiplier,
  stability,
}: {
  animationRegion?: LivePortraitAnimationRegion;
  strength?: LivePortraitMotionStrength;
  drivingMultiplier?: number;
  stability?: Partial<Pick<LivePortraitMotionConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion">>;
} = {}): LivePortraitMotionConfig {
  const resolvedDrivingMultiplier = drivingMultiplier ?? LIVEPORTRAIT_STRENGTH_MULTIPLIERS[strength];
  if (!Number.isFinite(resolvedDrivingMultiplier) || resolvedDrivingMultiplier < 0.5 || resolvedDrivingMultiplier > 1.5) {
    throw new Error("动作幅度必须在 0.5 到 1.5 之间");
  }
  return {
    ...LIVEPORTRAIT_DEFAULT_MOTION_CONFIG,
    ...stability,
    animation_region: animationRegion,
    driving_multiplier: resolvedDrivingMultiplier,
  };
}

export function parseLivePortraitMotionConfig(raw: unknown): LivePortraitMotionConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("LivePortrait 动作配置必须是对象");
  }
  const input = raw as Record<string, unknown>;
  const knownKeys = new Set(Object.keys(LIVEPORTRAIT_DEFAULT_MOTION_CONFIG));
  const unknownKey = Object.keys(input).find((key) => !knownKeys.has(key));
  if (unknownKey) throw new Error(`动作创建不支持参数 ${unknownKey}`);
  const animationRegion = input.animation_region;
  if (!LIVEPORTRAIT_ANIMATION_REGIONS.includes(animationRegion as LivePortraitAnimationRegion)) {
    throw new Error("迁移内容必须是 all、exp、pose 或 eyes");
  }
  const drivingMultiplier = input.driving_multiplier;
  if (typeof drivingMultiplier !== "number" || !Number.isFinite(drivingMultiplier) || drivingMultiplier < 0.5 || drivingMultiplier > 1.5) {
    throw new Error("动作幅度必须在 0.5 到 1.5 之间");
  }
  const booleanKeys = ["flag_stitching", "flag_pasteback", "flag_normalize_lip", "flag_relative_motion"] as const;
  for (const key of booleanKeys) {
    if (typeof input[key] !== "boolean") throw new Error(`${key} 必须是布尔值`);
  }
  return {
    animation_region: animationRegion as LivePortraitAnimationRegion,
    driving_multiplier: drivingMultiplier,
    flag_stitching: input.flag_stitching as boolean,
    flag_pasteback: input.flag_pasteback as boolean,
    flag_normalize_lip: input.flag_normalize_lip as boolean,
    flag_relative_motion: input.flag_relative_motion as boolean,
  };
}
