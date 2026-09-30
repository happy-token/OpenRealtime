import { afterEach, describe, expect, it, vi } from "vitest";
import { createAccessibleAvatar } from "./avatar-catalog-client";

afterEach(() => vi.unstubAllGlobals());

describe("accessible avatar creation", () => {
  it("uses the signed-in owner's catalog when the shared studio is unavailable", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ error: "不允许创建 Avatar" }, { status: 403 }))
      .mockResolvedValueOnce(Response.json({ avatar: { avatar_id: "avatar-personal-created" } }, { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    const avatar = await createAccessibleAvatar({
      displayName: "个人形象",
      sourceImageDataUrl: "data:image/jpeg;base64,/9j/2Q==",
    });
    expect(avatar.avatar_id).toBe("avatar-personal-created");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/avatars", "/api/user/avatars"]);
    expect((fetcher.mock.calls[1][1] as RequestInit).body).toBeInstanceOf(FormData);
  });
});
