"use client";
import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import { useEffect, useState } from "react";
import type { ConversationHistoryItem } from "@/lib/conversation-history";
import { ROLE_MODE_LABELS, isRolePresentationMode } from "@/lib/role-records";
import { readJsonResponse } from "@/lib/http-json-response";
import { ChatView } from "@/components/chat/chat-view";
import styles from "./conversation-history-screen.module.css";
import Link from "next/link";
import { conversationContinuationUrl } from "@/lib/conversation-continuation";

export function ConversationSessionLink({ sessionId, canViewDiagnostics }: { sessionId?: string | null; canViewDiagnostics: boolean }) {
  if (!canViewDiagnostics || !sessionId) return null;
  return <p>Session ID：<Link className={styles.continueButton} href={`/settings/session-diagnostics/sessions/${encodeURIComponent(sessionId)}`}>{sessionId}</Link></p>;
}

export function ConversationDetailScreen({ id, canViewDiagnostics = false }: { id: string; canViewDiagnostics?: boolean }) {
  const { t } = useLanguage();
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const updated = () => setRefresh((value) => value + 1);
    window.addEventListener("openrealtime:conversations-updated", updated);
    return () => window.removeEventListener("openrealtime:conversations-updated", updated);
  }, []);
  const [item, setItem] = useState<ConversationHistoryItem | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setItem(null);
    setError("");
    void fetch(`/api/conversations/${encodeURIComponent(id)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const payload = await readJsonResponse<{ conversation?: ConversationHistoryItem; error?: string }>(response, "对话读取失败");
        if (!response.ok || !payload.conversation) throw new Error(payload.error || "对话读取失败");
        if (!controller.signal.aborted) setItem(payload.conversation);
      }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "对话读取失败"); });
    return () => controller.abort();
  }, [id, refresh]);

  const continuationUrl = item ? conversationContinuationUrl(item) : null;

  return <div className={styles.detail}>
    <header><BackLink href="/conversations" label={t("返回对话记录")} />{item ? <><h1>{item.title}</h1><p>{item.role_name} · {isRolePresentationMode(item.mode) ? ROLE_MODE_LABELS[item.mode] : item.mode} · {new Date(item.started_at).toLocaleString("zh-CN")}</p></> : null}</header>
    {error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
    {!item && !error ? <p className={styles.empty}>{t("正在读取对话…")}</p> : null}
    {item ? <div className={styles.detailActions}><span>{item.entries.length}{t(" 条消息")}</span>{continuationUrl ? <Link className={styles.continueButton} href={continuationUrl}>{t("继续此对话")}</Link> : null}</div> : null}
    <ConversationSessionLink sessionId={item?.voice_session_id} canViewDiagnostics={canViewDiagnostics} />
    {item ? <div className={styles.transcript}><ChatView entries={item.entries} /></div> : null}
  </div>;
}
