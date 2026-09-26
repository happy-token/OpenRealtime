import type { Metadata } from "next";
import { MemorySettingsScreen } from "@/components/settings/memory-settings-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata: Metadata = { title: "Memory 与隐私 — OpenRealtime" };

export default function MemorySettingsPage() {
  return <WorkspaceShell><MemorySettingsScreen /></WorkspaceShell>;
}
