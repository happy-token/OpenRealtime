import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({
  user: vi.fn(), personal: vi.fn(), shared: vi.fn(), read: vi.fn(), write: vi.fn(), authorized: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/avatar-assets-server", () => ({ authorizeAvatarAssetRequest: dependencies.authorized }));
vi.mock("@/lib/personal-role-library", () => ({ findPersonalRole: dependencies.personal }));
vi.mock("@/lib/role-catalog-repository", () => ({ findRole: dependencies.shared }));
vi.mock("@/lib/user-default-role", () => ({ readUserDefaultRole: dependencies.read, writeUserDefaultRole: dependencies.write }));

import { GET, PUT } from "./route";
import { LOCAL_DEFAULT_ROLE_OWNER, localDefaultRoleOwnerForPage } from "@/lib/default-role-owner";

const account = { issuer: "test", subject: "user-one" };
const put = (roleId: string) => new Request("http://localhost:3010/api/user/default-role", {
  method: "PUT", headers: { origin: "http://localhost:3010", "content-type": "application/json" }, body: JSON.stringify({ roleId }),
});

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.user.mockResolvedValue(account);
  dependencies.authorized.mockReturnValue(false);
  dependencies.read.mockResolvedValue(null);
  dependencies.write.mockResolvedValue(undefined);
});

describe("per-user default role", () => {
  it("reads the user's saved role and falls back to the built-in assistant", async () => {
    expect(await (await GET(new Request("http://localhost:3010/api/user/default-role"))).json()).toEqual({ roleId: "default-assistant" });
    dependencies.read.mockResolvedValue("role-personal-123");
    expect(await (await GET(new Request("http://localhost:3010/api/user/default-role"))).json()).toEqual({ roleId: "role-personal-123" });
    expect(dependencies.read).toHaveBeenCalledWith(account);
  });

  it("allows an owned personal role and stores the choice for this user", async () => {
    dependencies.personal.mockResolvedValue({ role_id: "role-personal-123" });
    const response = await PUT(put("role-personal-123"));
    expect(response.status).toBe(200);
    expect(dependencies.personal).toHaveBeenCalledWith(account, "role-personal-123");
    expect(dependencies.write).toHaveBeenCalledWith(account, "role-personal-123");
  });

  it("rejects a personal role that the user cannot access", async () => {
    dependencies.personal.mockResolvedValue(null);
    expect((await PUT(put("role-personal-other"))).status).toBe(404);
    expect(dependencies.write).not.toHaveBeenCalled();
  });

  it("saves and reads a shared role in authorized local admin mode", async () => {
    dependencies.user.mockResolvedValue(null);
    dependencies.authorized.mockReturnValue(true);
    dependencies.shared.mockResolvedValue({ role_id: "role-avatar-123" });
    expect((await PUT(put("role-avatar-123"))).status).toBe(200);
    expect(dependencies.write).toHaveBeenCalledWith(LOCAL_DEFAULT_ROLE_OWNER, "role-avatar-123");
    dependencies.read.mockResolvedValue("role-avatar-123");
    expect(await (await GET(new Request("http://localhost:3010/api/user/default-role"))).json()).toEqual({ roleId: "role-avatar-123" });
    expect(dependencies.read).toHaveBeenCalledWith(LOCAL_DEFAULT_ROLE_OWNER);
  });

  it("keeps local fallback limited to a loopback development page", () => {
    const env = { NODE_ENV: "development", AVATAR_LOCAL_TEST_MODE: "true", AVATAR_EVALUATION_LOOPBACK_BOUND: "true" } as const;
    expect(localDefaultRoleOwnerForPage("127.0.0.1:3010", env)).toEqual(LOCAL_DEFAULT_ROLE_OWNER);
    expect(localDefaultRoleOwnerForPage("example.com", env)).toBeNull();
    expect(localDefaultRoleOwnerForPage("127.0.0.1:3010", { ...env, NODE_ENV: "production" })).toBeNull();
  });
});
