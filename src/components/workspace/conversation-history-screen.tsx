"use client";
import { useLanguage } from "@/components/language/language-provider";

import { SelectMenu } from "@/components/ui/select-menu";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pencil, Search, Trash2 } from "lucide-react";
import type { ConversationHistoryItem } from "@/lib/conversation-history";
import { ROLE_MODE_LABELS, isRolePresentationMode } from "@/lib/role-records";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./conversation-history-screen.module.css";

type Summary = Omit<ConversationHistoryItem, "owner_id" | "entries"> & { entry_count: number };

export function ConversationHistoryScreen() {
  const { t } = useLanguage();
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const updated = () => setRefresh((value) => value + 1);
    window.addEventListener("openrealtime:conversations-updated", updated);
    return () => window.removeEventListener("openrealtime:conversations-updated", updated);
  }, []);
  const params = useSearchParams();
  const [items, setItems] = useState<Summary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [role, setRole] = useState(params.get("role") ?? "");
  const [mode, setMode] = useState("");
  const [period, setPeriod] = useState("all");
  const [action, setAction] = useState<{ type: "rename" | "delete"; item: Summary } | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const savingRef = useRef(false);

  useEffect(() => {
    if (action && !dialogRef.current?.open) dialogRef.current?.showModal();
  }, [action]);

  function openAction(type: "rename" | "delete", item: Summary) {
    setTitle(item.title);
    setActionError("");
    setAction({ type, item });
  }

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/conversations", { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ conversations?: Summary[]; error?: string }>(response, "对话历史读取失败")
        .then((payload) => { if (!response.ok) throw new Error(payload.error || "对话历史读取失败"); return payload; }))
      .then((payload) => { if (!controller.signal.aborted) { setItems(payload.conversations ?? []); setError(""); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "对话历史读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  const roles = useMemo(() => [...new Map(items.filter((item) => item.role_id).map((item) => [item.role_id, item.role_name])).entries()], [items]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const cutoff = period === "7d" ? Date.now() - 7 * 86_400_000 : period === "30d" ? Date.now() - 30 * 86_400_000 : 0;
    return items.filter((item) => (!needle || `${item.title} ${item.role_name}`.toLocaleLowerCase().includes(needle))
      && (!role || item.role_id === role) && (!mode || item.mode === mode)
      && (!cutoff || Date.parse(item.updated_at) >= cutoff));
  }, [items, mode, period, query, role]);

  async function submitAction() {
    if (!action || savingRef.current) return;
    savingRef.current = true;
    setBusy(true);
    setActionError("");
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(action.item.id)}`, action.type === "delete" ? { method: "DELETE" } : {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }),
      });
      const payload = await readJsonResponse<{ title?: string; error?: string }>(response, "对话操作失败");
      if (!response.ok) throw new Error(payload.error || "对话操作失败");
      if (action.type === "rename" && !payload.title) throw new Error("对话改名失败");
      setItems((current) => action.type === "delete" ? current.filter((item) => item.id !== action.item.id) : current.map((item) => item.id === action.item.id ? { ...item, title: payload.title! } : item));
      setAction(null);
      window.dispatchEvent(new Event("openrealtime:conversations-updated"));
    } catch (cause) { setActionError(cause instanceof Error ? cause.message : "对话操作失败"); }
    finally { savingRef.current = false; setBusy(false); }
  }

  return <div className={styles.page}>
    <header><h1>{t("对话记录")}</h1><p>{t("按角色、方式和时间查找对话；删除后无法恢复。")}</p></header>
    <div className={styles.filters}>
      <label><Search /><input aria-label={t("搜索对话记录")} placeholder={t("搜索对话")} value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <SelectMenu fullWidth value={String(role)} ariaLabel={t("按角色筛选")} options={[{ value: "", label: t("全部角色") }, ...(roles.map(([id, name]) => ({ value: String(id ?? ""), label: String(name) })))]} onChange={value => setRole(value)} />
      <SelectMenu fullWidth value={String(mode)} ariaLabel={t("按呈现方式筛选")} options={[{ value: "", label: t("全部方式") }, ...([...new Set(items.map((item) => item.mode))].map((item) => ({ value: String(item), label: t(String(isRolePresentationMode(item) ? ROLE_MODE_LABELS[item] : item)) })))]} onChange={value => setMode(value)} />
      <SelectMenu fullWidth value={String(period)} ariaLabel={t("按时间筛选")} options={[{ value: "all", label: t("全部时间") }, { value: "7d", label: t("最近 7 天") }, { value: "30d", label: t("最近 30 天") }]} onChange={value => setPeriod(value)} />
    </div>
    {!loading && !error ? <p className={styles.resultCount}>{filtered.length}{t(" 段对话")}</p> : null}
    {error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
    {loading ? <p className={styles.empty}>{t("正在读取对话记录…")}</p> : filtered.length ? <div className={styles.list}>{filtered.map((item) => <article key={item.id}>
      <Link href={`/conversations/${encodeURIComponent(item.id)}`}><strong>{item.title}</strong><small className={styles.metadata}><span>{item.role_name}</span><span>{isRolePresentationMode(item.mode) ? ROLE_MODE_LABELS[item.mode] : item.mode}</span><span>{item.entry_count}{t(" 条消息")}</span><time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleString("zh-CN")}</time></small></Link>
      <div className={styles.rowActions}><button type="button" title={t("修改名称")} aria-label={t("修改对话名称 ") + item.title} onClick={() => openAction("rename", item)}><Pencil /></button><button type="button" title={t("删除")} aria-label={t("删除对话 ") + item.title} onClick={() => openAction("delete", item)}><Trash2 /></button></div>
    </article>)}</div> : !error ? <p className={styles.empty}>{t("没有匹配的对话记录")}</p> : null}
    {action ? <dialog ref={dialogRef} className={styles.actionDialog} aria-labelledby="conversation-action-title" onCancel={(event) => { if (savingRef.current) event.preventDefault(); else setAction(null); }}>
      <form onSubmit={(event) => { event.preventDefault(); void submitAction(); }}>
        <h2 id="conversation-action-title">{t(action.type === "rename" ? "修改对话名称" : "删除这段对话？")}</h2>
        {action.type === "rename" ? <label>{t("对话名称")}<input autoFocus aria-label={t("对话名称")} value={title} maxLength={80} required disabled={busy} onChange={(event) => setTitle(event.target.value)} /></label> : <p>{action.item.title}<br />{t("删除后无法恢复。")}</p>}
        {actionError ? <p role="alert" className={styles.error}>{t(actionError)}</p> : null}
        <footer><button type="button" disabled={busy} onClick={() => setAction(null)}>{t("取消")}</button><button type="submit" disabled={busy || (action.type === "rename" && !title.trim())}>{t(busy ? "正在处理…" : action.type === "rename" ? "保存" : "确认删除")}</button></footer>
      </form>
    </dialog> : null}
  </div>;
}
