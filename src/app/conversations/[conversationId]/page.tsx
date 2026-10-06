import type { Metadata } from "next";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { ConversationDetailScreen } from "@/components/workspace/conversation-detail-screen";
import { headers } from "next/headers";
import { userFromRequest } from "@/lib/user-session";
import { isAppAdmin } from "@/lib/app-admin-accounts";

export const metadata: Metadata = { title: "历史对话 — OpenRealtime" };
export default async function ConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  const user = await userFromRequest(new Request("http://localhost", { headers: await headers() }));
  const canViewDiagnostics = user ? await isAppAdmin(user) : false;
  return <WorkspaceShell><ConversationDetailScreen id={(await params).conversationId} canViewDiagnostics={canViewDiagnostics} /></WorkspaceShell>;
}
