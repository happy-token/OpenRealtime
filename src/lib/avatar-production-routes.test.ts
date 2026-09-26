import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: (href: string) => { throw new Error(`redirect:${href}`); },
}));

import MotionServicePage from "@/app/services/motion/page";
import TalkingServicePage from "@/app/services/talking/page";
import CreateAvatarPage from "@/app/avatars/create/page";

describe("legacy Avatar production routes", () => {
  it("redirects motion creation into the shared resource-library workbench", async () => {
    await expect(MotionServicePage({
      searchParams: Promise.resolve({
        avatar_id: "avatar-personal-123",
        return_to: "role-personal-456",
      }),
    })).rejects.toThrow("redirect:/resources?tab=avatars&task=motion&avatar_id=avatar-personal-123&return_to=role-personal-456");
  });

  it("redirects talking-material creation with its parent action and generation method", async () => {
    await expect(TalkingServicePage({
      searchParams: Promise.resolve({
        avatar_id: "avatar-personal-123",
        action_id: "action-idle",
        return_to: "role-personal-456",
        method: "lipforcing",
      }),
    })).rejects.toThrow("redirect:/resources?tab=avatars&task=talking&avatar_id=avatar-personal-123&action_id=action-idle&return_to=role-personal-456&method=lipforcing");
  });

  it("redirects the former Avatar Studio action entry into the same resource-library workbench", async () => {
    await expect(CreateAvatarPage({
      searchParams: Promise.resolve({
        task: "action",
        avatar_id: "avatar-personal-123",
        return_to: "role-personal-456",
      }),
    })).rejects.toThrow("redirect:/resources?tab=avatars&task=motion&avatar_id=avatar-personal-123&return_to=role-personal-456");
  });
});
