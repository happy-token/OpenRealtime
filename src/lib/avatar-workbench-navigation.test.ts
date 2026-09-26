import { describe, expect, it } from "vitest";
import { avatarResourceHref } from "./avatar-workbench-navigation";

describe("avatarResourceHref", () => {
  it("opens the shared motion workbench with the current Avatar and role context", () => {
    expect(avatarResourceHref({
      task: "motion",
      avatarId: "avatar-personal-123",
      returnTo: "role-personal-456",
    })).toBe("/resources?tab=avatars&task=motion&avatar_id=avatar-personal-123&return_to=role-personal-456");
  });
});
