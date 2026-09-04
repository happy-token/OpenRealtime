import { describe, expect, it } from "vitest";
import { fitAvatarImageDimensions } from "./avatar-image-normalization";

describe("avatar image normalization", () => {
  it("keeps a small image at its original dimensions", () => {
    expect(fitAvatarImageDimensions(800, 1200)).toEqual({ width: 800, height: 1200 });
  });

  it("bounds the longest edge without changing the aspect ratio", () => {
    expect(fitAvatarImageDimensions(4000, 3000)).toEqual({ width: 1280, height: 960 });
    expect(fitAvatarImageDimensions(2000, 4000)).toEqual({ width: 640, height: 1280 });
  });

  it("rejects invalid dimensions", () => {
    expect(() => fitAvatarImageDimensions(0, 100)).toThrow("尺寸无效");
  });
});
