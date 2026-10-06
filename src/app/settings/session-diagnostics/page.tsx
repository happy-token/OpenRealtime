import { headers } from "next/headers";
import { AdminLoginRedirect } from "@/components/admin/admin-login-redirect";
import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { isAppAdmin } from "@/lib/app-admin-accounts";
import { userFromRequest } from "@/lib/user-session";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const request = new Request("http://localhost", { headers: await headers() });
  const user = await userFromRequest(request);
  if (!user) return <AdminLoginRedirect />;
  if (!await isAppAdmin(user)) {
    return <WorkspaceShell><h1>会话诊断</h1><p role="alert">当前账号没有管理员权限，请联系管理员授权。</p></WorkspaceShell>;
  }
  return <AdminDashboard username={user.subject} />;
}
