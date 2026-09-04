export type LivePortraitRetargetConfig = {
  eye_open_delta: number;
  head_pitch: number;
  head_yaw: number;
  head_roll: number;
  smile: number;
  eyebrow: number;
  gaze_x: number;
  gaze_y: number;
  move_x: number;
  move_y: number;
  zoom: number;
  flag_stitching: boolean;
  flag_pasteback: boolean;
};

export const LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG: LivePortraitRetargetConfig = {
  eye_open_delta: 0,
  head_pitch: 0,
  head_yaw: 0,
  head_roll: 0,
  smile: 0,
  eyebrow: 0,
  gaze_x: 0,
  gaze_y: 0,
  move_x: 0,
  move_y: 0,
  zoom: 1,
  flag_stitching: true,
  flag_pasteback: true,
};

const NUMBER_RANGES = {
  eye_open_delta: [-0.3, 0.3],
  head_pitch: [-15, 15],
  head_yaw: [-25, 25],
  head_roll: [-15, 15],
  smile: [-0.3, 1.3],
  eyebrow: [-30, 30],
  gaze_x: [-30, 30],
  gaze_y: [-63, 63],
  move_x: [-0.19, 0.19],
  move_y: [-0.19, 0.19],
  zoom: [0.9, 1.2],
} as const satisfies Record<keyof Omit<LivePortraitRetargetConfig, "flag_stitching" | "flag_pasteback">, readonly [number, number]>;

export function createLivePortraitRetargetConfig(
  overrides: Partial<LivePortraitRetargetConfig> = {},
): LivePortraitRetargetConfig {
  return parseLivePortraitRetargetConfig({
    ...LIVEPORTRAIT_DEFAULT_RETARGET_CONFIG,
    ...overrides,
  });
}

export function parseLivePortraitRetargetConfig(raw: unknown): LivePortraitRetargetConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("LivePortrait 姿态配置必须是对象");
  }
  const record = raw as Record<string, unknown>;
  const allowed = new Set([...Object.keys(NUMBER_RANGES), "flag_stitching", "flag_pasteback"]);
  const unknown = Object.keys(record).find((key) => !allowed.has(key));
  if (unknown) throw new Error(`LivePortrait 姿态配置包含未知字段：${unknown}`);

  const parsed = {} as LivePortraitRetargetConfig;
  for (const [key, [minimum, maximum]] of Object.entries(NUMBER_RANGES) as Array<[
    keyof typeof NUMBER_RANGES,
    readonly [number, number],
  ]>) {
    const value = record[key];
    if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
      throw new Error(`${key} 必须在 ${minimum} 到 ${maximum} 之间`);
    }
    parsed[key] = value;
  }
  for (const key of ["flag_stitching", "flag_pasteback"] as const) {
    if (typeof record[key] !== "boolean") throw new Error(`${key} 必须是布尔值`);
    parsed[key] = record[key];
  }
  return parsed;
}
