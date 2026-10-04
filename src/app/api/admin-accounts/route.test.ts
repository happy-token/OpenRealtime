import { beforeEach, expect, it, vi } from "vitest";
import { GET, POST, DELETE } from "./route";
const mocks = vi.hoisted(() => ({ authorize: vi.fn(), list: vi.fn(), revoke: vi.fn(), find: vi.fn(), grant: vi.fn() }));
vi.mock("@/lib/admin-server", () => ({
  isAuthorizedForAdminAccountManagement: mocks.authorize,
  currentAppAdmin: async () => ({ issuer: "actor", subject: "actor" }), currentAdmin: async () => null,
}));
vi.mock("@/lib/app-admin-accounts", () => ({ listAppAdmins: mocks.list, revokeAppAdmin: mocks.revoke, grantAppAdmin: mocks.grant }));
vi.mock("@/lib/user-session", () => ({ findUserBySubject: mocks.find }));
const request = (method: string, body = {}) => new Request("https://app.example/api/admin-accounts", {
  method, headers: { origin: "https://app.example", "Content-Type": "application/json" },
  ...(method === "GET" ? {} : { body: JSON.stringify(body) }),
});
beforeEach(() => { vi.resetAllMocks(); mocks.authorize.mockResolvedValue(true); });
it("returns JSON 503 for authorization database failures on every method", async () => {
  mocks.authorize.mockRejectedValue(new Error("database unavailable"));
  for (const method of [GET, POST, DELETE]) {
    const response = await method(request(method === GET ? "GET" : method === POST ? "POST" : "DELETE"));
    expect(response.status).toBe(503);
    expect(await response.json()).toHaveProperty("error");
  }
});
it("requires an issuer for ambiguous admin subjects and revokes the exact account", async () => {
  const admins = [{ issuer: "a", subject: "same" }, { issuer: "b", subject: "same" }];
  mocks.list.mockResolvedValue(admins);
  expect((await DELETE(request("DELETE", { subject: "same" }))).status).toBe(400);
  expect(mocks.revoke).not.toHaveBeenCalled();
  mocks.revoke.mockResolvedValue("deleted");
  expect((await DELETE(request("DELETE", { subject: "same", issuer: "b" }))).status).toBe(200);
  expect(mocks.revoke).toHaveBeenCalledWith(admins[1]);
});
it("honors the transactional last-admin check", async () => {
  mocks.list.mockResolvedValue([{ issuer: "a", subject: "same" }]);
  mocks.revoke.mockResolvedValue("last-admin");
  expect((await DELETE(request("DELETE", { subject: "same", issuer: "a" }))).status).toBe(400);
});
it("rejects ambiguous grants and passes the explicit issuer to identity lookup", async () => {
  mocks.find.mockRejectedValue(new Error("账号 ID 对应多个身份来源，请填写 issuer"));
  expect((await POST(request("POST", { subject: "same" }))).status).toBe(400);
  mocks.find.mockResolvedValue({ issuer: "b", subject: "same" }); mocks.list.mockResolvedValue([]);
  expect((await POST(request("POST", { subject: "same", issuer: "b" }))).status).toBe(200);
  expect(mocks.find).toHaveBeenLastCalledWith("same", "b");
});
