import { describe, expect, it } from "vitest";
import { classifyMediaAspectRatio } from "./media-aspect-fit";

describe("classifyMediaAspectRatio", () => {
  it("classifies wide media as landscape", () => {
    expect(classifyMediaAspectRatio(1920, 1080)).toBe("landscape");
    expect(classifyMediaAspectRatio(1.2, 1)).toBe("landscape");
  });

  it("classifies tall media as portrait", () => {
    expect(classifyMediaAspectRatio(1080, 1920)).toBe("portrait");
    expect(classifyMediaAspectRatio(0.82, 1)).toBe("portrait");
  });

  it("classifies near-square media as square", () => {
    expect(classifyMediaAspectRatio(1, 1)).toBe("square");
    expect(classifyMediaAspectRatio(1.1, 1)).toBe("square");
    expect(classifyMediaAspectRatio(0.9, 1)).toBe("square");
  });

  it("falls back to square for zero or negative dimensions", () => {
    expect(classifyMediaAspectRatio(0, 0)).toBe("square");
    expect(classifyMediaAspectRatio(-1, 100)).toBe("square");
    expect(classifyMediaAspectRatio(100, -1)).toBe("square");
  });
});
