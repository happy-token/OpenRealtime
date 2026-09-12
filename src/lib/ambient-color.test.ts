import { describe, expect, it } from "vitest";
import { getEdgeAmbientColor } from "./ambient-color";

describe("getEdgeAmbientColor", () => {
  it("uses the image edge instead of the center subject", () => {
    const pixels = new Uint8ClampedArray(5 * 5 * 4);
    for (let index = 0; index < pixels.length; index += 4) pixels.set([32, 72, 112, 255], index);
    pixels.set([246, 204, 169, 255], (2 * 5 + 2) * 4);

    expect(getEdgeAmbientColor(pixels, 5, 5)).toBe("rgb(32 72 112)");
  });

  it("ignores transparent edge pixels", () => {
    const pixels = new Uint8ClampedArray(3 * 3 * 4);
    for (let index = 0; index < pixels.length; index += 4) pixels.set([12, 24, 36, 255], index);
    pixels.set([255, 0, 0, 0], 0);

    expect(getEdgeAmbientColor(pixels, 3, 3)).toBe("rgb(12 24 36)");
  });
});
