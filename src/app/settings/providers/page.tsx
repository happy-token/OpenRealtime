import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ADMIN_SESSION_COOKIE, adminAuthConfigFromEnv, verifyAdminSessionToken } from "@/lib/admin-auth";
import { ProviderSettingsScreen } from "@/components/settings/provider-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "供应商设置 — OpenRealtime" };

export default async function ProviderSettingsPage() {
  const admin = adminAuthConfigFromEnv();
  const showPlatformModelServices = Boolean(admin && verifyAdminSessionToken((await cookies()).get(ADMIN_SESSION_COOKIE)?.value, admin));
  return <WorkspaceShell><ProviderSettingsScreen showPlatformModelServices={showPlatformModelServices} /></WorkspaceShell>;
}
