import type { Metadata } from "next";
import { AccountSettingsScreen } from "@/components/settings/account-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "设置 — OpenRealtime" };

export default function SettingsPage() {
  return <WorkspaceShell><AccountSettingsScreen section="settings" /></WorkspaceShell>;
}
