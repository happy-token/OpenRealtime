import { describe, expect, it, vi } from "vitest";
import {
  AnamAvatarError,
  createAnamAvatar,
  listAnamAvatars,
  updateAnamAvatarName,
} from "./anam-avatars";

const environment = { ANAM_API_KEY: "anam-key" };

describe("Anam hosted avatar catalog", () => {
  it("normalizes official and organization-created avatars without exposing credentials", async () => {
    const fetcher = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response(
      JSON.stringify({
        data: [
          {
            id: "official-cara",
            displayName: "Cara",
            imageUrl: "https://cdn.example/cara.jpg",
            videoUrl: null,
            createdByOrganizationId: null,
            availableVersions: ["cara-3"],
            activeVersion: "cara-3",
          },
          {
            id: "my-avatar",
            displayName: "My Avatar",
            imageUrl: "https://cdn.example/mine.jpg",
            videoUrl: "https://cdn.example/mine.mp4",
            createdByOrganizationId: "org-1",
            availableVersions: ["cara-4-latest"],
            activeVersion: "cara-4-latest",
          },
        ],
        meta: { total: 2, currentPage: 1, lastPage: 1, perPage: 100, next: null },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));

    await expect(listAnamAvatars(environment, fetcher as typeof fetch)).resolves.toEqual({
      avatars: [
        expect.objectContaining({ id: "official-cara", origin: "official" }),
        expect.objectContaining({ id: "my-avatar", origin: "personal" }),
      ],
      total: 2,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "https://api.anam.ai/v1/avatars?page=1&perPage=100",
      expect.objectContaining({
        headers: { Authorization: "Bearer anam-key" },
        cache: "no-store",
      }),
    );
  });

  it("creates a hosted avatar from an accepted source image", async () => {
    const fetcher = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response(
      JSON.stringify({
        id: "created-avatar",
        displayName: "Cyber Friend",
        imageUrl: "https://cdn.example/created.jpg",
        videoUrl: null,
        createdByOrganizationId: "org-1",
        availableVersions: ["cara-4-latest"],
        activeVersion: "cara-4-latest",
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    ));
    const image = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], "identity.jpg", { type: "image/jpeg" });

    const result = await createAnamAvatar(
      environment,
      { displayName: "Cyber Friend", image, avatarModel: "cara-4-latest" },
      fetcher as typeof fetch,
    );

    expect(result).toEqual(expect.objectContaining({ id: "created-avatar", origin: "personal" }));
    const options = fetcher.mock.calls[0]?.[1];
    expect(options?.headers).toEqual({ Authorization: "Bearer anam-key" });
    expect(options?.body).toBeInstanceOf(FormData);
    const form = options?.body as FormData;
    expect(form.get("displayName")).toBe("Cyber Friend");
    expect(form.get("avatarModel")).toBe("cara-4-latest");
    expect(form.get("imageFile")).toBe(image);
  });

  it("updates the display name of an existing hosted avatar", async () => {
    const fetcher = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response(
      JSON.stringify({
        id: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
        displayName: "傻妞",
        imageUrl: "https://cdn.example/shuchang.jpg",
        videoUrl: null,
        createdByOrganizationId: "org-1",
        availableVersions: ["cara-4"],
        activeVersion: "cara-4",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));

    await expect(updateAnamAvatarName(
      environment,
      { avatarId: "9437f771-e41a-4e7a-92ed-c9c813020a8b", displayName: " 傻妞 " },
      fetcher as typeof fetch,
    )).resolves.toEqual(expect.objectContaining({
      id: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
      displayName: "傻妞",
      origin: "personal",
    }));
    expect(fetcher).toHaveBeenCalledWith(
      "https://api.anam.ai/v1/avatars/9437f771-e41a-4e7a-92ed-c9c813020a8b",
      expect.objectContaining({
        method: "PUT",
        headers: {
          Authorization: "Bearer anam-key",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ displayName: "傻妞" }),
      }),
    );
  });

  it("applies the three-character minimum only when creating an Anam avatar", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const image = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], "identity.jpg", { type: "image/jpeg" });

    await expect(createAnamAvatar(
      environment,
      { displayName: "两字", image },
      fetcher,
    )).rejects.toEqual(new AnamAvatarError("Anam 形象名称需要 3 到 50 个字符", 400));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("maps invalid credentials and malformed payloads to safe provider errors", async () => {
    const rejected = vi.fn(async () => new Response(
      JSON.stringify({ message: "private provider detail" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ));
    await expect(listAnamAvatars(environment, rejected as typeof fetch))
      .rejects.toEqual(new AnamAvatarError("Anam API Key 无效", 401));

    const malformed = vi.fn(async () => new Response("{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    await expect(listAnamAvatars(environment, malformed as typeof fetch))
      .rejects.toEqual(new AnamAvatarError("Anam 返回了无效的形象目录", 502));
  });

  it("reports create permission failures separately from invalid keys", async () => {
    const forbidden = vi.fn(async () => new Response(
      JSON.stringify({ message: "private provider detail" }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    ));
    const image = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], "identity.jpg", { type: "image/jpeg" });

    await expect(createAnamAvatar(
      environment,
      { displayName: "测试形象", image, avatarModel: "cara-4" },
      forbidden as typeof fetch,
    )).rejects.toEqual(new AnamAvatarError("当前 Anam API Key 没有创建形象的权限", 403));
  });
});
