import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { currentAppAdmin } from "@/lib/admin-server";
import { DecisionLogScreen } from "@/components/settings/decision-log-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "决策日志 — OpenRealtime" };

export default async function DiagnosticsSettingsPage() {
  const requestHeaders = await headers();
  const admin = await currentAppAdmin(new Request("http://localhost", { headers: requestHeaders }));
  if (!admin) redirect("/settings");
  return <WorkspaceShell><DecisionLogScreen /></WorkspaceShell>;
}
