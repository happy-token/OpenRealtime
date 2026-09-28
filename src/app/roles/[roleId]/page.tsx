import type { Metadata } from "next";
import { RoleDetailScreen } from "@/components/roles/role-detail-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "角色配置 — OpenRealtime" };

export default async function RolePage({ params, searchParams }: {
  params: Promise<{ roleId: string }>;
  searchParams: Promise<{ settings?: string }>;
}) {
  const { roleId } = await params;
  const query = await searchParams;
  return <WorkspaceShell><RoleDetailScreen roleId={roleId} initialSettingsOpen={query.settings === "1"} /></WorkspaceShell>;
}
