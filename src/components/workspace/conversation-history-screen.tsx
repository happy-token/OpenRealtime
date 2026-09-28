"use client";
import { SelectMenu } from "@/components/ui/select-menu";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Search, Trash2 } from "lucide-react";
import type { ConversationHistoryItem } from "@/lib/conversation-history";
import { ROLE_MODE_LABELS, isRolePresentationMode } from "@/lib/role-records";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./conversation-history-screen.module.css";

type Summary = Omit<ConversationHistoryItem, "owner_id" | "entries"> & { entry_count: number };

export function ConversationHistoryScreen() {
  const params = useSearchParams();
  const [items, setItems] = useState<Summary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [role, setRole] = useState(params.get("role") ?? "");
  const [mode, setMode] = useState("");
  const [period, setPeriod] = useState("all");
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/conversations", { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ conversations?: Summary[]; error?: string }>(response, "对话历史读取失败")
        .then((payload) => { if (!response.ok) throw new Error(payload.error || "对话历史读取失败"); return payload; }))
      .then((payload) => { if (!controller.signal.aborted) setItems(payload.conversations ?? []); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "对话历史读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  const roles = useMemo(() => [...new Map(items.filter((item) => item.role_id).map((item) => [item.role_id, item.role_name])).entries()], [items]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const cutoff = period === "7d" ? Date.now() - 7 * 86_400_000 : period === "30d" ? Date.now() - 30 * 86_400_000 : 0;
    return items.filter((item) => (!needle || `${item.title} ${item.role_name}`.toLocaleLowerCase().includes(needle))
      && (!role || item.role_id === role) && (!mode || item.mode === mode)
      && (!cutoff || Date.parse(item.updated_at) >= cutoff));
  }, [items, mode, period, query, role]);

  async function remove(id: string) {
    setError("");
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error("删除对话失败");
      setItems((current) => current.filter((item) => item.id !== id));
      setDeleting(null);
      window.dispatchEvent(new Event("openrealtime:conversations-updated"));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "删除对话失败"); }
  }

  return <div className={styles.page}>
    <header><h1>对话记录</h1><p>按角色、方式和时间查找对话；删除后无法恢复。</p></header>
    <div className={styles.filters}>
      <label><Search /><input aria-label="搜索对话记录" placeholder="搜索对话" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <SelectMenu fullWidth value={String(role)} ariaLabel="按角色筛选" options={[{ value: "", label: "全部角色" }, ...(roles.map(([id, name]) => ({ value: String(id ?? ""), label: String(name) })))]} onChange={value => setRole(value)} />
      <SelectMenu fullWidth value={String(mode)} ariaLabel="按呈现方式筛选" options={[{ value: "", label: "全部方式" }, ...([...new Set(items.map((item) => item.mode))].map((item) => ({ value: String(item), label: String(isRolePresentationMode(item) ? ROLE_MODE_LABELS[item] : item) })))]} onChange={value => setMode(value)} />
      <SelectMenu fullWidth value={String(period)} ariaLabel="按时间筛选" options={[{ value: "all", label: "全部时间" }, { value: "7d", label: "最近 7 天" }, { value: "30d", label: "最近 30 天" }]} onChange={value => setPeriod(value)} />
    </div>
    {error ? <p role="alert" className={styles.error}>{error}</p> : null}
    {loading ? <p className={styles.empty}>正在读取对话记录…</p> : filtered.length ? <div className={styles.list}>{filtered.map((item) => <article key={item.id}>
      <Link href={`/conversations/${encodeURIComponent(item.id)}`}><strong>{item.title}</strong><small>{item.role_name} · {isRolePresentationMode(item.mode) ? ROLE_MODE_LABELS[item.mode] : item.mode} · {new Date(item.updated_at).toLocaleString("zh-CN")} · {item.entry_count} 条消息</small></Link>
      <button type="button" aria-label={`删除对话 ${item.title}`} onClick={() => setDeleting(item.id)}><Trash2 /></button>
    </article>)}</div> : <p className={styles.empty}>没有匹配的对话记录</p>}
    {deleting ? <div className={styles.backdrop}><div role="alertdialog" aria-modal="true" aria-label="确认删除对话"><h2>删除这段对话？</h2><p>删除后无法恢复。</p><div><button type="button" onClick={() => setDeleting(null)}>取消</button><button type="button" onClick={() => void remove(deleting)}>确认删除</button></div></div></div> : null}
  </div>;
}
