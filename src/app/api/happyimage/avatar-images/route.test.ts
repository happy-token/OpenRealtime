import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const provider = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock("@/lib/happyimage-avatar", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/happyimage-avatar")>(),
  createHappyImageAvatar: provider.create,
}));

import { POST } from "./route";

afterEach(() => vi.clearAllMocks());

describe("HappyImage Avatar route", () => {
  it("returns an owned generated image without exposing credentials", async () => {
    provider.create.mockResolvedValue({ imageUrl: "data:image/png;base64,AA==", taskId: "task-1" });
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/happyimage/avatar-images", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: "portrait" }),
    }));

    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ imageUrl: "data:image/png;base64,AA==" });
    expect(provider.create).toHaveBeenCalledWith(expect.any(Object), { prompt: "portrait" });
  });
});
