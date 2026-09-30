import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const provider = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  updateName: vi.fn(),
}));
const account = vi.hoisted(() => ({ user: vi.fn(), personalKey: vi.fn() }));

vi.mock("@/lib/user-session", () => ({ userFromRequest: account.user }));
vi.mock("@/lib/user-provider-credentials", () => ({ loadPersonalKey: account.personalKey }));

vi.mock("@/lib/anam-avatars", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/anam-avatars")>();
  return {
    ...original,
    listAnamAvatars: provider.list,
    createAnamAvatar: provider.create,
    updateAnamAvatarName: provider.updateName,
  };
});

import { GET, POST, PUT } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  account.user.mockResolvedValue(null);
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
  vi.stubEnv("ANAM_API_KEY", "anam-key");
  vi.stubEnv("ANAM_AVATAR_MODEL", "cara-4");
}

function requestHeaders(extra: Record<string, string> = {}) {
  return {
    host: "127.0.0.1:3010",
    origin: "http://127.0.0.1:3010",
    "sec-fetch-site": "same-origin",
    ...extra,
  };
}

describe("Anam hosted avatar catalog route", () => {
  it("reads the catalog with the signed-in user's configured Anam key", async () => {
    account.user.mockResolvedValue({ issuer: "test", subject: "alice" });
    account.personalKey.mockResolvedValue("alice-anam-key");
    provider.list.mockResolvedValue({ avatars: [{ id: "alice-avatar", origin: "personal" }], total: 1 });
    const response = await GET(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      headers: requestHeaders(),
    }));
    expect(response.status).toBe(200);
    expect(provider.list).toHaveBeenCalledWith({ ANAM_API_KEY: "alice-anam-key" });
    await expect(response.json()).resolves.toMatchObject({ configured: true, avatars: [{ id: "alice-avatar" }] });
  });
  it("uses a signed-in user's own key and avoids a second Anam registration", async () => {
    account.user.mockResolvedValue({ issuer: "test", subject: "alice" });
    account.personalKey.mockResolvedValue("alice-anam-key");
    provider.list.mockResolvedValue({ avatars: [{ id: "already-created", origin: "personal" }], total: 1 });
    const form = new FormData();
    form.set("displayName", "New Avatar");
    form.set("image", new File([Uint8Array.from([0xff, 0xd8, 0xff, 0xd9])], "portrait.jpg", { type: "image/jpeg" }));
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      method: "POST",
      headers: requestHeaders({ "content-length": "1024" }),
      body: form,
    }));
    expect(response.status).toBe(409);
    expect(provider.list).toHaveBeenCalledWith({ ANAM_API_KEY: "alice-anam-key" });
    expect(provider.create).not.toHaveBeenCalled();
  });
  it("rejects unauthenticated catalog reads", async () => {
    const response = await GET(new NextRequest("http://127.0.0.1:3010/api/anam/avatars"));
    expect(response.status).toBe(403);
  });

  it("synchronizes the provider catalog in local test mode", async () => {
    enableLocalTestMode();
    provider.list.mockResolvedValue({
      avatars: [{ id: "my-avatar", displayName: "Mine", origin: "personal" }],
      total: 1,
    });
    const response = await GET(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      headers: requestHeaders(),
    }));
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ configured: true, connected: true, total: 1 });
    expect(provider.list).toHaveBeenCalledWith({ ANAM_API_KEY: "anam-key" });
  });

  it("creates without redundant browser consent checkboxes", async () => {
    enableLocalTestMode();
    provider.create.mockResolvedValue({ id: "created", displayName: "Cyber Friend", origin: "personal" });
    const form = new FormData();
    form.set("displayName", "Cyber Friend");
    form.set("image", new File([Uint8Array.from([0xff, 0xd8, 0xff, 0xd9])], "portrait.jpg", { type: "image/jpeg" }));
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      method: "POST",
      headers: requestHeaders({ "content-length": "1024" }),
      body: form,
    }));
    expect(response.status).toBe(201);
    expect(provider.create).toHaveBeenCalledOnce();
  });

  it("creates a hosted avatar and returns the refreshed provider asset", async () => {
    enableLocalTestMode();
    provider.create.mockResolvedValue({ id: "created", displayName: "Cyber Friend", origin: "personal" });
    const form = new FormData();
    form.set("displayName", "Cyber Friend");
    form.set("image", new File([Uint8Array.from([0xff, 0xd8, 0xff, 0xd9])], "portrait.jpg", { type: "image/jpeg" }));
    const response = await POST(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      method: "POST",
      headers: requestHeaders({ "content-length": "1024" }),
      body: form,
    }));
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toMatchObject({ avatar: { id: "created" } });
    expect(provider.create).toHaveBeenCalledWith(
      { ANAM_API_KEY: "anam-key" },
      expect.objectContaining({ displayName: "Cyber Friend", avatarModel: "cara-4" }),
    );
  });

  it("renames a hosted avatar from a same-origin request", async () => {
    enableLocalTestMode();
    provider.updateName.mockResolvedValue({
      id: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
      displayName: "Shuchang",
      origin: "personal",
    });
    const response = await PUT(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      method: "PUT",
      headers: requestHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({
        avatarId: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
        displayName: "Shuchang",
      }),
    }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      avatar: { id: "9437f771-e41a-4e7a-92ed-c9c813020a8b", displayName: "Shuchang" },
    });
    expect(provider.updateName).toHaveBeenCalledWith(
      { ANAM_API_KEY: "anam-key" },
      {
        avatarId: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
        displayName: "Shuchang",
      },
    );
  });

  it("rejects cross-origin avatar rename requests", async () => {
    enableLocalTestMode();
    const response = await PUT(new NextRequest("http://127.0.0.1:3010/api/anam/avatars", {
      method: "PUT",
      headers: requestHeaders({ origin: "https://attacker.example", "content-type": "application/json" }),
      body: JSON.stringify({
        avatarId: "9437f771-e41a-4e7a-92ed-c9c813020a8b",
        displayName: "Hijacked",
      }),
    }));

    expect(response.status).toBe(403);
    expect(provider.updateName).not.toHaveBeenCalled();
  });
});
