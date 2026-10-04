import { beforeEach, expect, it, vi } from "vitest";
import AdminPage from "@/app/admin/page";
const mocks = vi.hoisted(() => ({ user: vi.fn(), admin: vi.fn() }));
vi.mock("next/headers", () => ({ headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({ redirect: (path: string) => { throw new Error(`redirect:${path}`); } }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.user }));
vi.mock("@/lib/app-admin-accounts", () => ({ isAppAdmin: mocks.admin }));
vi.mock("@/components/admin/admin-dashboard", () => ({ AdminDashboard: () => null }));
vi.mock("@/components/workspace/workspace-shell", () => ({ WorkspaceShell: () => null }));
beforeEach(() => { vi.resetAllMocks(); mocks.user.mockResolvedValue(null); mocks.admin.mockResolvedValue(false); });
it("opens the dashboard directly using the existing administrator account session", async () => {
  mocks.user.mockResolvedValue({ issuer: "issuer", subject: "account" });
  mocks.admin.mockResolvedValue(true);
  expect((await AdminPage()).props).toMatchObject({ username: "account" });
  expect(mocks.admin).toHaveBeenCalledWith({ issuer: "issuer", subject: "account" });
});
it("uses the application login only when the application session is absent", async () => {
  await expect(AdminPage()).rejects.toThrow("redirect:/api/user/login?next=%2Fadmin");
});
it("does not prompt a logged-in non-admin to log in again", async () => {
  mocks.user.mockResolvedValue({ issuer: "issuer", subject: "user" });
  const page = await AdminPage();
  expect(page.props.children[1].props.children).toContain("没有管理员权限");
});
it("does not turn a database outage into a second login prompt", async () => {
  mocks.user.mockRejectedValue(new Error("database unavailable"));
  await expect(AdminPage()).rejects.toThrow("database unavailable");
});
