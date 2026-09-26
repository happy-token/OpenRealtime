import { describe, expect, it } from "vitest";
import { avatarApiRoot } from "./avatar-catalog-client";

describe("Avatar API routing", () => {
  it("routes personal avatar talking-material mutations through owner-scoped APIs", () => {
    expect(avatarApiRoot("avatar-personal-123")).toBe("/api/user/avatars");
    expect(avatarApiRoot("shared-avatar")).toBe("/api/avatars");
  });
});
