import type { Metadata } from "next";
import { RoleListScreen } from "@/components/roles/role-list-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "角色 — OpenRealtime" };

export default function RolesPage() {
  return <WorkspaceShell><RoleListScreen /></WorkspaceShell>;
}

