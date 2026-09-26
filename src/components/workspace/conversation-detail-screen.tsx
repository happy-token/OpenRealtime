"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { ConversationHistoryItem } from "@/lib/conversation-history";
import { ROLE_MODE_LABELS, isRolePresentationMode } from "@/lib/role-records";
import { readJsonResponse } from "@/lib/http-json-response";
import { ChatView } from "@/components/chat/chat-view";
import styles from "./conversation-history-screen.module.css";

export function ConversationDetailScreen({ id }: { id: string }) {
  const [item, setItem] = useState<ConversationHistoryItem | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`/api/conversations/${encodeURIComponent(id)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const payload = await readJsonResponse<{ conversation?: ConversationHistoryItem; error?: string }>(response, "对话读取失败");
        if (!response.ok || !payload.conversation) throw new Error(payload.error || "对话读取失败");
        if (!controller.signal.aborted) setItem(payload.conversation);
      }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "对话读取失败"); });
    return () => controller.abort();
  }, [id]);

  return <div className={styles.detail}>
    <header><Link href="/conversations"><ArrowLeft />对话记录</Link>{item ? <><h1>{item.title}</h1><p>{item.role_name} · {isRolePresentationMode(item.mode) ? ROLE_MODE_LABELS[item.mode] : item.mode} · {new Date(item.started_at).toLocaleString("zh-CN")}</p></> : null}</header>
    {error ? <p role="alert" className={styles.error}>{error}</p> : null}
    {!item && !error ? <p className={styles.empty}>正在读取对话…</p> : null}
    {item ? <div className={styles.transcript}><ChatView entries={item.entries} /></div> : null}
  </div>;
}
