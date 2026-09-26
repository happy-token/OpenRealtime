import type { Metadata } from "next";
import { Suspense } from "react";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { ConversationHistoryScreen } from "@/components/workspace/conversation-history-screen";

export const metadata: Metadata = { title: "对话记录 — OpenRealtime" };
export default function ConversationsPage() { return <WorkspaceShell><Suspense><ConversationHistoryScreen /></Suspense></WorkspaceShell>; }
