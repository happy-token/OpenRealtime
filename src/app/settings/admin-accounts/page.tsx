import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { isAuthorizedForAdminAccountManagement } from "@/lib/admin-server";
import { AdminAccountsScreen } from "@/components/settings/admin-accounts-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "管理员账号 — OpenRealtime" };

export default async function AdminAccountsPage() {
  const requestHeaders = await headers();
  const authorized = await isAuthorizedForAdminAccountManagement(
    new Request("http://localhost", { headers: requestHeaders }),
  );
  if (!authorized) redirect("/settings");
  return <WorkspaceShell><AdminAccountsScreen /></WorkspaceShell>;
}
