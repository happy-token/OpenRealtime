import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ origin: vi.fn(), user: vi.fn(), update: vi.fn() }));
vi.mock("@/lib/avatar-test-access", () => ({ isSameOriginAvatarMutation: dependencies.origin }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/personal-avatar-library", () => ({ updatePersonalTalkingVariant: dependencies.update }));

import { PATCH } from "./route";

const user = { issuer: "test", subject: "alice" };
const context = { params: Promise.resolve({ avatarId: "avatar-personal-123", avatarActionId: "motion-123", variantId: "lipforcing-123" }) };
const request = (body: object) => new NextRequest("http://localhost:3010/api/user/avatars/avatar-personal-123/actions/motion-123/talking-variants/lipforcing-123", {
  method: "PATCH",
  headers: { origin: "http://localhost:3010", "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.origin.mockReturnValue(true);
  dependencies.user.mockResolvedValue(user);
  dependencies.update.mockResolvedValue({ avatar_action_id: "motion-123", talking_variants: [{ id: "lipforcing-123", display_name: "新口型对齐" }] });
});

describe("personal talking material management", () => {
  it("renames the current user's talking material", async () => {
    const response = await PATCH(request({ operation: "rename", displayName: "新口型对齐" }), context);

    expect(response.status).toBe(200);
    expect(dependencies.update).toHaveBeenCalledWith(user, "avatar-personal-123", "motion-123", "lipforcing-123", { displayName: "新口型对齐" });
  });

  it.each(["replace", "trash", "restore"])("rejects the unsupported %s operation", async (operation) => {
    const response = await PATCH(request({ operation }), context);

    expect(response.status).toBe(400);
    expect(dependencies.update).not.toHaveBeenCalled();
  });
});
