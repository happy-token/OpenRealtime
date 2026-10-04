import type { Metadata } from "next";
import { ToolPermissionsScreen } from "@/components/settings/tool-permissions-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "工具权限 — OpenRealtime" };

export default function ToolPermissionsPage() {
  return <WorkspaceShell><ToolPermissionsScreen /></WorkspaceShell>;
}
