import type { Metadata } from "next";
import { RoleDetailScreen } from "@/components/roles/role-detail-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "角色配置 — OpenRealtime" };

export default async function RolePage({ params }: { params: Promise<{ roleId: string }> }) {
  const { roleId } = await params;
  return <WorkspaceShell><RoleDetailScreen roleId={roleId} /></WorkspaceShell>;
}
