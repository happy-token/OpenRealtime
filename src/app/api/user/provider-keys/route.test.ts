import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const store = vi.hoisted(() => ({
  user: vi.fn(), list: vi.fn(), save: vi.fn(), remove: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: store.user }));
vi.mock("@/lib/user-provider-credentials", () => ({
  listPersonalKeyStatuses: store.list,
  savePersonalKey: store.save,
  deletePersonalKey: store.remove,
  parsePersonalKeyProvider: (value: unknown) => value === "anam" ? "anam" : null,
}));

import { DELETE, GET, POST } from "./route";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function request(method: "GET" | "POST" | "DELETE", origin = "https://example.test") {
  return new NextRequest("https://example.test/api/user/provider-keys?provider=anam", {
    method,
    headers: { origin, "content-type": "application/json" },
    body: method === "POST" ? JSON.stringify({ provider: "anam", apiKey: "personal-secret-key" }) : undefined,
  });
}

describe("account API key settings", () => {
  it("requires a signed-in user before reading or writing", async () => {
    store.user.mockResolvedValue(null);
    expect((await GET(request("GET"))).status).toBe(401);
    expect((await POST(request("POST"))).status).toBe(401);
    expect((await DELETE(request("DELETE"))).status).toBe(401);
    expect(store.save).not.toHaveBeenCalled();
  });

  it("returns masked status without plaintext and saves only to the owner", async () => {
    const user = { issuer: "https://identity.test", subject: "person-1" };
    store.user.mockResolvedValue(user);
    store.list.mockResolvedValue([{ provider: "anam", configured: true, suffix: "-key" }]);
    vi.stubEnv("ANAM_API_KEY", "platform-secret-key");
    const status = await GET(request("GET"));
    expect(status.status).toBe(200);
    const body = await status.text();
    expect(body).not.toContain("personal-secret-key");
    expect(body).not.toContain("platform-secret-key");
    expect(JSON.parse(body).credentials[0]).toMatchObject({ provider: "anam", suffix: "-key",
      platformConfigured: true, platformSuffix: "-key" });
    const saved = await POST(request("POST"));
    expect(saved.status).toBe(200);
    expect(store.save).toHaveBeenCalledWith(user, "anam", "personal-secret-key");
  });

  it("rejects cross-origin deletion and deletes only the authenticated user's provider", async () => {
    const user = { issuer: "https://identity.test", subject: "person-1" };
    store.user.mockResolvedValue(user);
    expect((await DELETE(request("DELETE", "https://attacker.test"))).status).toBe(403);
    expect(store.remove).not.toHaveBeenCalled();
    expect((await DELETE(request("DELETE"))).status).toBe(200);
    expect(store.remove).toHaveBeenCalledWith(user, "anam");
  });

  it("rejects an oversized key submission before saving it", async () => {
    store.user.mockResolvedValue({ issuer: "https://identity.test", subject: "person-1" });
    const oversized = new NextRequest("https://example.test/api/user/provider-keys", {
      method: "POST",
      headers: { origin: "https://example.test", "content-type": "application/json" },
      body: JSON.stringify({ provider: "anam", apiKey: "x".repeat(3000) }),
    });
    expect((await POST(oversized)).status).toBe(413);
    expect(store.save).not.toHaveBeenCalled();
  });
});
