import { afterEach, describe, expect, it, vi } from "vitest";
import { saveGeneratedPersonalAction } from "./personal-action-client";

describe("personal action client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("saves a generated motion and binds it to the role draft avatar as one operation", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ asset: { id: "a".repeat(64) } }, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ action: {
        avatar_action_id: "motion-new",
        display_name: "自然待机",
        video_url: `/api/user/motion-assets/${"a".repeat(64)}?preview=1`,
      } }, { status: 201 }));
    vi.stubGlobal("fetch", fetcher);

    const action = await saveGeneratedPersonalAction({
      taskId: "task-123456",
      avatarId: "avatar-personal-123",
    });

    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/user/motion-assets", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ taskId: "task-123456" }),
    }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/user/avatars/avatar-personal-123/actions", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ motionId: "a".repeat(64) }),
    }));
    expect(action.avatar_action_id).toBe("motion-new");
  });

  it("does not bind an action when saving the generated motion fails", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: "动作素材保存失败" }, { status: 502 }));
    vi.stubGlobal("fetch", fetcher);

    await expect(saveGeneratedPersonalAction({
      taskId: "task-123456",
      avatarId: "avatar-personal-123",
    })).rejects.toThrow("动作素材保存失败");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
