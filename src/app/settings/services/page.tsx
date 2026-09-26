import { AccountSettingsScreen } from "@/components/settings/account-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export default function ServicesPage() {
  return <WorkspaceShell><AccountSettingsScreen section="services" /></WorkspaceShell>;
}
