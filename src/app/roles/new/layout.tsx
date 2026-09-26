import type { ReactNode } from "react";
import { RoleCreationWorkbenchProvider } from "@/components/roles/role-creation-workbench-context";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export default function NewRoleLayout({ children }: { children: ReactNode }) {
  return <RoleCreationWorkbenchProvider><WorkspaceShell>{children}</WorkspaceShell></RoleCreationWorkbenchProvider>;
}
