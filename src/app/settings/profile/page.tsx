import { AccountSettingsScreen } from "@/components/settings/account-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export default function ProfilePage() {
  return <WorkspaceShell><AccountSettingsScreen section="profile" /></WorkspaceShell>;
}

