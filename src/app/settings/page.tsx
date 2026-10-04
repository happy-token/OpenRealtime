import type { Metadata } from "next";
import { headers } from "next/headers";
import { currentAppAdmin } from "@/lib/admin-server";
import { AccountSettingsScreen } from "@/components/settings/account-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "设置 — OpenRealtime" };

export default async function SettingsPage() {
  const requestHeaders = await headers();
  const admin = await currentAppAdmin(new Request("http://localhost", { headers: requestHeaders }));
  return <WorkspaceShell><AccountSettingsScreen section="settings" showDiagnostics={Boolean(admin)} /></WorkspaceShell>;
}
