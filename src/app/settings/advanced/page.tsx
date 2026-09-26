import type { Metadata } from "next";
import { AdvancedSettingsScreen } from "@/components/settings/advanced-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "高级配置 — OpenRealtime" };

export default function AdvancedSettingsPage() {
  return <WorkspaceShell><AdvancedSettingsScreen /></WorkspaceShell>;
}
