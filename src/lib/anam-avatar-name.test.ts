import { describe, expect, it } from "vitest";
import {
  isValidAnamAvatarName,
  suggestAnamAvatarName,
} from "./anam-avatar-name";

describe("Anam avatar names", () => {
  it("keeps valid names and expands short local names for provider creation", () => {
    expect(isValidAnamAvatarName("陪伴数字人")).toBe(true);
    expect(isValidAnamAvatarName("陪伴")).toBe(false);
    expect(suggestAnamAvatarName("陪伴")).toBe("陪伴数字人");
    expect(suggestAnamAvatarName("Shuchang")).toBe("Shuchang");
  });
});
