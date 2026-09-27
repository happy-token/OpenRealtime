import { afterEach, expect, it, vi } from "vitest";
import { ADMIN_SESSION_COOKIE, createAdminSessionToken } from "./admin-auth";

const user = vi.hoisted(() => ({ current: vi.fn() }));
vi.mock("./user-session", () => ({ userFromRequest: user.current }));
import { providerActor } from "./provider-instance-access";

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });

it("accepts an administrator without granting personal ownership", async () => {
  const config = { username: "admin", password: "long-password-123", sessionSecret: "s".repeat(32) };
  vi.stubEnv("VOICEAGENT_ADMIN_USERNAME", config.username);
  vi.stubEnv("VOICEAGENT_ADMIN_PASSWORD", config.password);
  vi.stubEnv("VOICEAGENT_ADMIN_SESSION_SECRET", config.sessionSecret);
  user.current.mockResolvedValue(null);
  const request = new Request("https://app.test/api/provider-instances", { headers: {
    cookie: `${ADMIN_SESSION_COOKIE}=${createAdminSessionToken(config)}`,
  } });
  expect(await providerActor(request)).toEqual({ user: { issuer: "platform", subject: "admin" },
    admin: true, signedIn: false });
});

it("rejects an invalid admin cookie when there is no user session", async () => {
  user.current.mockResolvedValue(null);
  expect(await providerActor(new Request("https://app.test/api/provider-instances"))).toBeNull();
});
