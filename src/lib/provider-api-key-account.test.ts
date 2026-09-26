import { afterEach, describe, expect, it, vi } from "vitest";

const account = vi.hoisted(() => ({
  user: vi.fn(), key: vi.fn(),
}));
vi.mock("./user-session", () => ({ userFromRequest: account.user }));
vi.mock("./user-provider-credentials", () => ({ loadPersonalKey: account.key }));

import { resolveProviderApiKey } from "./provider-api-key";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("account provider key resolution", () => {
  const request = new Request("https://example.test/api/anam/session");
  const user = { issuer: "https://identity.test", subject: "person-1" };

  it("uses only the signed-in account's saved key when present", async () => {
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    account.user.mockResolvedValue(user);
    account.key.mockResolvedValue("personal-anam-key");
    await expect(resolveProviderApiKey(request, "anam")).resolves.toBe("personal-anam-key");
    expect(account.key).toHaveBeenCalledWith(user, "anam");
  });

  it("uses the platform key only when no personal key is saved", async () => {
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    account.user.mockResolvedValue(user);
    account.key.mockResolvedValue(null);
    await expect(resolveProviderApiKey(request, "anam")).resolves.toBe("platform-anam-key");
  });

  it("does not silently use the platform key when account storage fails", async () => {
    vi.stubEnv("ANAM_API_KEY", "platform-anam-key");
    account.user.mockResolvedValue(user);
    account.key.mockRejectedValue(new Error("database unavailable"));
    await expect(resolveProviderApiKey(request, "anam")).rejects.toThrow("database unavailable");
  });
});
