import { describe, expect, it } from "vitest";
import { describeNextSteps, inspectAvatarImage } from "./role-avatar-composer";

describe("role avatar composer", () => {
  it("describes only the downstream tasks required by selected modes", () => {
    expect(describeNextSteps(["conversation"])).toBe("形象创建后返回角色任务清单");
    expect(describeNextSteps(["conversation", "realtime"])).toBe("形象创建后继续配置：实时驱动");
    expect(describeNextSteps(["offline", "lip-sync"])).toBe("形象创建后继续配置：动作底片、口型对齐");
    expect(describeNextSteps(["realtime", "offline", "lip-sync"])).toBe("形象创建后继续配置：实时驱动、动作底片、口型对齐");
  });

  it("turns image dimensions and bytes into useful quality guidance", () => {
    expect(inspectAvatarImage(1080, 1920, 1_200_000).map((item) => item.tone)).toEqual(["good", "good", "good"]);
    expect(inspectAvatarImage(420, 2400, 3_400_000).map((item) => item.tone)).toEqual(["warn", "warn", "warn"]);
    expect(inspectAvatarImage(0, 0, 0)).toEqual([]);
  });
});
