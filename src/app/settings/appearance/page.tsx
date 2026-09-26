import type { Metadata } from "next";
import { AppearanceSettingsScreen } from "@/components/settings/appearance-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "外观设置 — OpenRealtime" };

export default function AppearanceSettingsPage() {
  return <WorkspaceShell><AppearanceSettingsScreen /></WorkspaceShell>;
}
