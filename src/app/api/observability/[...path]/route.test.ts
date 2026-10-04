import { NextRequest } from "next/server";
import { expect, it, vi } from "vitest";
import { GET, DELETE } from "./route";
vi.mock("@/lib/admin-server", () => ({
  currentAppAdmin: async () => { throw new Error("database unavailable"); },
  currentAdmin: async () => null, isAdminConfigured: () => true,
}));
it("returns JSON 503 for GET and DELETE when the authorization store fails", async () => {
  const context = { params: Promise.resolve({ path: ["sessions"] }) };
  for (const handler of [GET, DELETE]) {
    const response = await handler(new NextRequest("https://app.example/api/observability/sessions"), context);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "管理员权限服务暂时不可用" });
  }
});
