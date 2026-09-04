import { describe, expect, it, vi } from "vitest";
import { createHappyImageAvatar, HappyImageAvatarError } from "./happyimage-avatar";

describe("HappyImage avatar client", () => {
  it("uses a server-side account key and returns an owned image copy", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "task-1", status: "queued" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: "task-1", status: "success", data: [{ url: "http://happy.test/images/lin.png" }] }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(Uint8Array.from([0x89, 0x50, 0x4e, 0x47]), { status: 200, headers: { "Content-Type": "image/png" } }));

    const result = await createHappyImageAvatar(
      { HAPPYIMAGE_API_URL: "http://happy.test", HAPPYIMAGE_API_KEY: "secret" },
      { prompt: "studio portrait" },
      fetcher,
      async () => undefined,
    );

    expect(result.imageUrl).toBe("data:image/png;base64,iVBORw==");
    expect(fetcher).toHaveBeenNthCalledWith(1, "http://happy.test/api/image-tasks/generations", expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer secret" }),
    }));
  });

  it("fails clearly when no linked HappyImage account is configured", async () => {
    await expect(createHappyImageAvatar({}, { prompt: "portrait" })).rejects.toEqual(
      expect.objectContaining<Partial<HappyImageAvatarError>>({ status: 503 }),
    );
  });
});
