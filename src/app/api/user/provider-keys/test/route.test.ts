import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const mocks = vi.hoisted(() => ({ user: vi.fn(), load: vi.fn(), check: vi.fn() }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.user }));
vi.mock("@/lib/user-provider-credentials", () => ({
  loadPersonalKey: mocks.load,
  parsePersonalKeyProvider: (value: unknown) => value === "deepseek" ? "deepseek" : null,
}));
vi.mock("@/lib/provider-credential-test", () => ({
  isTestableProvider: (value: unknown) => value === "deepseek",
  testProviderCredential: mocks.check,
}));

import { POST } from "./route";

afterEach(() => vi.clearAllMocks());

function request(body: object, origin = "https://example.test") {
  return new NextRequest("https://example.test/api/user/provider-keys/test", {
    method: "POST", headers: { origin, "content-type": "application/json" }, body: JSON.stringify(body),
  });
}

describe("supplier connection test API", () => {
  it("requires same origin and a signed-in user", async () => {
    expect((await POST(request({ provider: "deepseek" }, "https://other.test"))).status).toBe(403);
    mocks.user.mockResolvedValue(null);
    expect((await POST(request({ provider: "deepseek" }))).status).toBe(401);
    expect(mocks.check).not.toHaveBeenCalled();
  });

  it("tests the saved key or a draft key without returning the secret", async () => {
    const user = { issuer: "issuer", subject: "person" };
    mocks.user.mockResolvedValue(user);
    mocks.load.mockResolvedValue("saved-private-key");
    mocks.check.mockResolvedValue({ ok: true, message: "连接成功" });

    const saved = await POST(request({ provider: "deepseek" }));
    expect(saved.status).toBe(200);
    expect(mocks.load).toHaveBeenCalledWith(user, "deepseek");
    expect(mocks.check).toHaveBeenCalledWith("deepseek", "saved-private-key");
    expect(await saved.text()).not.toContain("saved-private-key");

    mocks.load.mockClear();
    await POST(request({ provider: "deepseek", apiKey: "draft-private-key" }));
    expect(mocks.load).not.toHaveBeenCalled();
    expect(mocks.check).toHaveBeenLastCalledWith("deepseek", "draft-private-key");
  });

  it("rejects malformed credentials before a vendor request", async () => {
    mocks.user.mockResolvedValue({ issuer: "issuer", subject: "person" });
    expect((await POST(request({ provider: "deepseek", apiKey: "bad\nkey" }))).status).toBe(400);
    expect(mocks.check).not.toHaveBeenCalled();
  });
});
