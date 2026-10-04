"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/components/language/language-provider";
import { readJsonResponse } from "@/lib/http-json-response";
import type { RecentConversation } from "@/lib/recent-conversations-client";
import styles from "./recent-conversation-actions.module.css";

export function RecentConversationActions({ item }: { item: RecentConversation }) {
  const { t } = useLanguage();
  const router = useRouter();
  const pathname = usePathname();
  const menuRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [action, setAction] = useState<"rename" | "delete" | null>(null);
  const [title, setTitle] = useState(item.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const href = `/conversations/${encodeURIComponent(item.id)}`;

  useEffect(() => { if (action) dialogRef.current?.showModal(); }, [action]);

  function openAction(value: "rename" | "delete") {
    menuRef.current?.hidePopover();
    setTitle(item.title);
    setError("");
    setAction(value);
  }

  async function submit() {
    if (!action || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(item.id)}`, action === "delete" ? { method: "DELETE" } : { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }) });
      const payload = await readJsonResponse<{ error?: string }>(response, "对话操作失败");
      if (!response.ok) throw new Error(payload.error || "对话操作失败");
      setAction(null);
      window.dispatchEvent(new Event("openrealtime:conversations-updated"));
      if (action === "delete" && pathname === href) router.replace("/conversations");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "对话操作失败"); }
    finally { submitting.current = false; setBusy(false); }
  }

  return <>
    <button className={styles.trigger} data-conversation-actions title={t("对话操作")} type="button" aria-label={t("对话操作 ") + item.title} aria-haspopup="menu" aria-expanded={menuOpen} aria-controls={`recent-menu-${item.id}`} onClick={(event) => {
      const menu = menuRef.current;
      if (!menu) return;
      const rect = event.currentTarget.getBoundingClientRect();
      menu.style.left = `${Math.max(8, Math.min(rect.right, window.innerWidth - 188))}px`;
      menu.style.top = `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 150))}px`;
      menu.togglePopover();
    }}><MoreHorizontal aria-hidden="true" /></button>
    <div id={`recent-menu-${item.id}`} ref={menuRef} popover="auto" onToggle={(event) => setMenuOpen(event.currentTarget.matches(":popover-open"))} onKeyDown={(event) => {
      const options = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
      const index = options.indexOf(document.activeElement as HTMLElement);
      const next = event.key === "ArrowDown" ? (index + 1) % options.length : event.key === "ArrowUp" ? (index + options.length - 1) % options.length : event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : null;
      if (next !== null) { event.preventDefault(); options[next]?.focus(); }
    }} className={styles.menu} role="menu" aria-label={t("对话操作 ") + item.title}>
      <Link role="menuitem" href={href} onClick={() => menuRef.current?.hidePopover()}>{t("查看记录")}</Link>
      <button type="button" role="menuitem" onClick={() => openAction("rename")}><Pencil />{t("修改名称")}</button>
      <button type="button" role="menuitem" onClick={() => openAction("delete")}><Trash2 />{t("删除")}</button>
    </div>
    {action ? <dialog ref={dialogRef} className={styles.dialog} aria-labelledby={`recent-action-${item.id}`} onCancel={(event) => { if (submitting.current) event.preventDefault(); else setAction(null); }}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <h2 id={`recent-action-${item.id}`}>{t(action === "rename" ? "修改对话名称" : "删除这段对话？")}</h2>
        {action === "rename" ? <label>{t("对话名称")}<input autoFocus aria-label={t("对话名称")} maxLength={80} required value={title} disabled={busy} onChange={(event) => setTitle(event.target.value)} /></label> : <p>{item.title}<br />{t("删除后无法恢复。")}</p>}
        {error ? <p role="alert">{t(error)}</p> : null}
        <footer><button type="button" disabled={busy} onClick={() => setAction(null)}>{t("取消")}</button><button type="submit" disabled={busy || (action === "rename" && !title.trim())}>{t(busy ? "正在处理…" : action === "rename" ? "保存" : "确认删除")}</button></footer>
      </form>
    </dialog> : null}
  </>;
}
