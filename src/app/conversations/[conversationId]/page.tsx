import type { Metadata } from "next";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { ConversationDetailScreen } from "@/components/workspace/conversation-detail-screen";

export const metadata: Metadata = { title: "历史对话 — OpenRealtime" };
export default async function ConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  return <WorkspaceShell><ConversationDetailScreen id={(await params).conversationId} /></WorkspaceShell>;
}
