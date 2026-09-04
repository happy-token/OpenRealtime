import { describe, expect, it } from "vitest";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  normalizeWorkbenchVisualPreferences,
  workbenchSurfaceTokens,
} from "./workbench-visual-preferences";

describe("workbench visual preferences", () => {
  it("keeps the configured transparency and blur within their supported ranges", () => {
    expect(normalizeWorkbenchVisualPreferences("80", "12")).toEqual({ transparency: 80, glassBlur: 12 });
    expect(normalizeWorkbenchVisualPreferences(null, null)).toEqual(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
    expect(normalizeWorkbenchVisualPreferences(99, -1)).toEqual(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  });

  it("derives one glass surface model for the workbench and session controls", () => {
    expect(workbenchSurfaceTokens({ transparency: 70, glassBlur: 10 })).toEqual({
      surfaceAlpha: "0.30",
      highlightAlpha: "0.072",
      softAlpha: "0.030",
      blur: "3px",
    });
  });
});
