"use client";
import { useLanguage } from "@/components/language/language-provider";

import { SelectMenu } from "@/components/ui/select-menu";

import { useEffect, useRef, useState } from "react";
import { fetchRoles, saveRole } from "@/lib/role-catalog-client";
import type { RoleRecord } from "@/lib/role-records";
import type { MemoryKind, MemoryRecord } from "@/lib/memory-catalog";
import { Plus, RefreshCw, X } from "lucide-react";
import styles from "./memory-settings-screen.module.css";

const KIND_LABELS: Record<MemoryKind, string> = { preference: "偏好", relationship: "关系", goal: "目标", correction: "纠正", fact: "个人信息" };

export function MemorySettingsScreen({ initialRoleId = "" }: { initialRoleId?: string } = {}) {
  const { t } = useLanguage();
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState(initialRoleId);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [kind, setKind] = useState<MemoryKind>("preference");
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const editorRef = useRef<HTMLDialogElement>(null);
  const selectedRole = roles.find((role) => role.role_id === selectedRoleId);
  const [filter, setFilter] = useState("");
  const visibleMemories = memories.filter((memory) => `${KIND_LABELS[memory.kind]} ${memory.content}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase().trim()));

  useEffect(() => {
    const controller = new AbortController();
    void fetchRoles(controller.signal).then((items) => { if (controller.signal.aborted) return; setRoles(items); setSelectedRoleId((old) => old || items[0]?.role_id || ""); if (!items.length && !initialRoleId) setLoading(false); }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : "角色读取失败"); setLoading(false); }
    });
    return () => controller.abort();
  }, [initialRoleId]);

  useEffect(() => {
    if (!selectedRoleId) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setMemories([]);
    setEditing(null);
    setContent("");
    void fetch(`/api/memory?roleId=${encodeURIComponent(selectedRoleId)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = await response.json() as { memories?: MemoryRecord[]; error?: string };
        if (!response.ok) throw new Error(data.error || "记忆读取失败");
        if (!controller.signal.aborted) setMemories(data.memories ?? []);
      }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "记忆读取失败"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selectedRoleId, refresh]);

  useEffect(() => { if (editorOpen) editorRef.current?.showModal(); }, [editorOpen]);
  function closeEditor() { editorRef.current?.close(); setEditorOpen(false); setEditing(null); setContent(""); }
  function openEditor(memory?: MemoryRecord) { setEditing(memory?.id ?? null); setKind(memory?.kind ?? "preference"); setContent(memory?.content ?? ""); setError(""); setEditorOpen(true); }

  async function mutate(method: "POST" | "PATCH" | "DELETE", body?: object, id?: string) {
    if (!selectedRoleId || loading || busy) return;
    setBusy(true);
    setError("");
    try {
      const url = `/api/memory?roleId=${encodeURIComponent(selectedRoleId)}${id ? `&id=${encodeURIComponent(id)}` : ""}`;
      const response = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
      const data = await response.json() as { memory?: MemoryRecord; error?: string };
      if (!response.ok) throw new Error(data.error || "记忆操作失败");
      if (method === "DELETE") setMemories((old) => id ? old.filter((item) => item.id !== id) : []);
      else if (data.memory) setMemories((old) => [data.memory!, ...old.filter((item) => item.id !== data.memory!.id)]);
      closeEditor();
      setNotice(method === "DELETE" ? "记忆已删除" : "记忆已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "记忆操作失败"); }
    finally { setBusy(false); }
  }

  async function updateRoleMemory(role: RoleRecord, enabled: boolean) {
    setSaving(role.role_id);
    setError("");
    try {
      const saved = await saveRole(role.role_id, {
        displayName: role.display_name,
        voiceProvider: role.voice_provider,
        voiceId: role.voice_id,
        personaId: role.persona_id,
        avatarId: role.avatar_id,
        enabledModes: role.enabled_modes,
        defaultMode: role.default_mode,
        memoryEnabled: enabled,
        modelId: role.model_id ?? null,
        toolIds: role.tool_ids,
      });
      setRoles((old) => old.map((item) => item.role_id === saved.role_id ? saved : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "记忆配置保存失败");
    } finally {
      setSaving(null);
    }
  }

  const disabled = busy || loading || saving !== null || !selectedRoleId;
  return <div className={styles.page}>
    <header className={styles.heading}><div><h2>{t("记忆管理")}</h2><p>{t("按角色查看和整理已保存的记忆。")}</p></div><button type="button" disabled={disabled} onClick={() => openEditor()}><Plus size={16} />{t("新增记忆")}</button></header>
    <section className={styles.roleRow} aria-label={t("角色记忆")}>
      <div><span>{t("角色")}</span><SelectMenu value={selectedRoleId} ariaLabel={t("角色")} options={roles.map((role) => ({ value: role.role_id, label: role.display_name }))} disabled={busy || saving !== null || editorOpen} onChange={(value) => { setSelectedRoleId(value); setMemories([]); setContent(""); setFilter(""); setNotice(""); }} /></div>
      {selectedRole ? <label className={styles.toggle}><span>{t("使用长期记忆")}</span><input type="checkbox" checked={selectedRole.memory_enabled} disabled={saving !== null || busy} onChange={(event) => void updateRoleMemory(selectedRole, event.target.checked)} /></label> : null}
    </section>
    <div className={styles.toolbar}><span>{t("已保存")}: {memories.length} / 100</span><div><input aria-label={t("搜索记忆")} placeholder={t("按内容搜索记忆")} value={filter} onChange={(event) => setFilter(event.target.value)} /><button type="button" className={styles.secondary} aria-label={t("刷新记忆")} disabled={disabled || editorOpen} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={16} /></button></div></div>
    {notice ? <p role="status" className={styles.notice}>{t(notice)}</p> : null}
    {!editorOpen && error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
    <section className={styles.list} aria-label={t("已保存的记忆")}>
      {loading ? <p role="status">{t("正在读取记忆…")}</p> : visibleMemories.map((memory) => <article key={memory.id} className={styles.memory}><div><small>{t(KIND_LABELS[memory.kind])}</small><p>{memory.content}</p><details><summary>{t("预览详情")}</summary><p>{t("更新时间")}: {new Date(memory.updated_at).toLocaleString()}</p><p>{t("来源")}: {memory.source_conversation_id ? t("对话自动提取") : t("手动添加")}</p></details></div><div className={styles.actions}><button type="button" className={styles.secondary} disabled={disabled} onClick={() => openEditor(memory)}>{t("编辑")}</button><button type="button" className={styles.secondary} disabled={disabled} onClick={() => { if (window.confirm("删除这条记忆？此操作无法恢复。")) void mutate("DELETE", undefined, memory.id); }}>{t("删除")}</button></div></article>)}
      {!loading && !error && !memories.length ? <p>{t(selectedRoleId ? "这个角色还没有保存的记忆。" : "请选择角色")}</p> : null}
      {!loading && memories.length > 0 && !visibleMemories.length ? <p>{t("没有匹配的记忆")}</p> : null}
    </section>
    <details className={styles.explanation}><summary>{t("记忆说明与清理")}</summary><p>{t("记忆按用户和角色隔离。关闭记忆后仍可整理记录，但对话不再读取或自动保存。清空记忆不会删除对话历史；需要清除当前上下文时请新建对话。")}</p><p>{t("每条最多 300 字符")}</p>{memories.length ? <button type="button" className={styles.secondary} disabled={disabled} onClick={() => { if (window.confirm("清空这个角色的全部记忆？此操作无法恢复。")) void mutate("DELETE"); }}>{t("清空当前角色记忆")}</button> : null}</details>
    {editorOpen ? <dialog ref={editorRef} className={styles.dialog} aria-labelledby="memory-editor-title" onCancel={(event) => { event.preventDefault(); if (!busy) closeEditor(); }}><header><h3 id="memory-editor-title">{t(editing ? "编辑记忆" : "新增记忆")}</h3><button type="button" className={styles.secondary} aria-label={t("关闭编辑")} disabled={busy} onClick={closeEditor}><X size={18} /></button></header><label>{t("类型")}<SelectMenu fullWidth value={kind} ariaLabel={t("类型")} disabled={busy || !!editing} options={Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label: t(label) }))} onChange={(value) => setKind(value as MemoryKind)} /></label><label>{t("记忆内容")}<textarea aria-label={t("记忆内容")} disabled={busy} value={content} maxLength={300} rows={5} onChange={(event) => setContent(event.target.value)} /></label>{error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}<footer><button type="button" className={styles.secondary} disabled={busy} onClick={closeEditor}>{t("取消")}</button><button type="button" disabled={busy || !content.trim()} onClick={() => void mutate(editing ? "PATCH" : "POST", editing ? { id: editing, content } : { kind, content })}>{t(busy ? "正在保存…" : editing ? "保存修改" : "添加记忆")}</button></footer></dialog> : null}
  </div>;
}
