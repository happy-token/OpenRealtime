import type { Metadata } from "next";
import { ProviderSettingsScreen } from "@/components/settings/provider-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "供应商设置 — OpenRealtime" };

export default function ProviderSettingsPage() {
  return <WorkspaceShell><ProviderSettingsScreen /></WorkspaceShell>;
}
