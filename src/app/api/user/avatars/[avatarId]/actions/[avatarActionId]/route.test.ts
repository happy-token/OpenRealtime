import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ origin: vi.fn(), user: vi.fn(), update: vi.fn() }));
vi.mock("@/lib/avatar-test-access", () => ({ isSameOriginAvatarMutation: dependencies.origin }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/personal-avatar-library", () => ({ updatePersonalAvatarAction: dependencies.update }));

import { PATCH } from "./route";

const user = { issuer: "test", subject: "alice" };
const context = { params: Promise.resolve({ avatarId: "avatar-personal-123", avatarActionId: "motion-123" }) };
const request = (body: object, origin = "http://localhost:3010") => new NextRequest("http://localhost:3010/api/user/avatars/avatar-personal-123/actions/motion-123", {
  method: "PATCH",
  headers: { origin, "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.origin.mockReturnValue(true);
  dependencies.user.mockResolvedValue(user);
  dependencies.update.mockResolvedValue({ avatar_action_id: "motion-123", display_name: "新动作" });
});

describe("personal avatar action management", () => {
  it("renames only the current user's action", async () => {
    const response = await PATCH(request({ operation: "rename", displayName: "新动作" }), context);

    expect(response.status).toBe(200);
    expect(dependencies.update).toHaveBeenCalledWith(user, "avatar-personal-123", "motion-123", { displayName: "新动作" });
  });

  it("rejects cross-origin updates before reading the user", async () => {
    dependencies.origin.mockReturnValue(false);
    const response = await PATCH(request({ operation: "trash" }, "https://attacker.example"), context);

    expect(response.status).toBe(403);
    expect(dependencies.user).not.toHaveBeenCalled();
    expect(dependencies.update).not.toHaveBeenCalled();
  });

  it.each(["trash", "restore"])("rejects the legacy %s lifecycle operation", async (operation) => {
    const response = await PATCH(request({ operation }), context);

    expect(response.status).toBe(400);
    expect(dependencies.update).not.toHaveBeenCalled();
  });
});
