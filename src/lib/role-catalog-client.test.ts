import { afterEach, describe, expect, it, vi } from "vitest";
import { createRole } from "./role-catalog-client";
const input = { displayName: "未命名角色", voiceProvider: "doubao" as const, voiceId: "test-voice", personaId: null, avatarId: null, enabledModes: ["conversation" as const], defaultMode: "conversation" as const, memoryEnabled: true, toolIds: [] };
afterEach(() => vi.unstubAllGlobals());
describe("role draft creation routing", () => {
  it("keeps signed-in creations in the personal library", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ role: { role_id: "role-personal-test" } }, { status: 201 })); vi.stubGlobal("fetch", fetch);
    expect((await createRole(input)).role_id).toBe("role-personal-test");
    expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0][0]).toBe("/api/user/roles");
  });
  it("creates a local draft only when the shared API authorizes it", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ error: "请先登录" }, { status: 401 })).mockResolvedValueOnce(Response.json({ role: { role_id: "role-local-test" } }, { status: 201 })); vi.stubGlobal("fetch", fetch);
    expect((await createRole(input)).role_id).toBe("role-local-test");
    expect(fetch.mock.calls.map(call => call[0])).toEqual(["/api/user/roles", "/api/roles"]);
    expect(fetch.mock.calls[1][1].body).toBe(JSON.stringify(input));
  });
  it("requires login when neither personal nor local creation is authorized", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ error: "请先登录" }, { status: 401 })).mockResolvedValueOnce(Response.json({ error: "不允许创建角色" }, { status: 403 })); vi.stubGlobal("fetch", fetch);
    await expect(createRole(input)).rejects.toMatchObject({ message: "请先登录后创建角色", status: 401 });
  });
  it("never redirects a personal validation or service failure into shared storage", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ error: "角色配置无效" }, { status: 400 })); vi.stubGlobal("fetch", fetch);
    await expect(createRole(input)).rejects.toThrow("角色配置无效"); expect(fetch).toHaveBeenCalledTimes(1);
  });
});
