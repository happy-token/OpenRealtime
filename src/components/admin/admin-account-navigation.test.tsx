import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const mocks = vi.hoisted(() => ({ user: vi.fn(), admin: vi.fn() }));
vi.mock("next/headers", () => ({ headers: async () => new Headers() }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.user }));
vi.mock("@/lib/app-admin-accounts", () => ({ isAppAdmin: mocks.admin }));
vi.mock("@/components/workspace/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/admin/admin-dashboard", () => ({ AdminDashboard: ({ username }: { username: string }) => <h1>{username} 后台</h1> }));
import AdminPage from "@/app/settings/session-diagnostics/page";

describe("admin account navigation", () => {
  beforeEach(() => vi.resetAllMocks());
  it("renders a document-login boundary for an expired session", async () => {
    mocks.user.mockResolvedValue(null);
    const html = renderToStaticMarkup(await AdminPage());
    expect(html).toContain('href="/api/user/login?next=%2Fsettings%2Fsession-diagnostics"');
    expect(mocks.admin).not.toHaveBeenCalled();
  });
  it("uses an existing admin account directly without a login redirect", async () => {
    const user = { issuer: "sso", subject: "admin" };
    mocks.user.mockResolvedValue(user);
    mocks.admin.mockResolvedValue(true);
    const html = renderToStaticMarkup(await AdminPage());
    expect(html).toContain("admin 后台");
    expect(html).not.toContain("/api/user/login");
    expect(mocks.admin).toHaveBeenCalledWith(user);
  });
  it("keeps signed-in accounts without a grant out of the dashboard", async () => {
    mocks.user.mockResolvedValue({ issuer: "sso", subject: "user" });
    mocks.admin.mockResolvedValue(false);
    const html = renderToStaticMarkup(await AdminPage());
    expect(html).toContain("当前账号没有管理员权限");
    expect(html).not.toContain("/api/user/login");
  });
});
