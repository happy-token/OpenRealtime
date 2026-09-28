"use client";
import { SelectMenu } from "@/components/ui/select-menu";

import { useEffect, useState } from "react";
import { fetchRoles, saveRole } from "@/lib/role-catalog-client";
import type { RoleRecord } from "@/lib/role-records";
import type { MemoryKind, MemoryRecord } from "@/lib/memory-catalog";
import styles from "./appearance-settings-screen.module.css";

const KIND_LABELS: Record<MemoryKind, string> = { preference: "偏好", relationship: "关系", goal: "目标", correction: "纠正" };

export function MemorySettingsScreen() {
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [kind, setKind] = useState<MemoryKind>("preference");
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void fetchRoles(controller.signal).then((items) => { setRoles(items); setSelectedRoleId((old) => old || items[0]?.role_id || ""); }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "角色读取失败");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedRoleId) return;
    const controller = new AbortController();
    void fetch(`/api/memory?roleId=${encodeURIComponent(selectedRoleId)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = await response.json() as { memories?: MemoryRecord[]; error?: string };
        if (!response.ok) throw new Error(data.error || "记忆读取失败");
        if (!controller.signal.aborted) setMemories(data.memories ?? []);
      }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "记忆读取失败"); });
    return () => controller.abort();
  }, [selectedRoleId]);

  async function mutate(method: "POST" | "PATCH" | "DELETE", body?: object, id?: string) {
    if (!selectedRoleId) return;
    setBusy(true);
    setError("");
    try {
      const url = `/api/memory?roleId=${encodeURIComponent(selectedRoleId)}${id ? `&id=${encodeURIComponent(id)}` : ""}`;
      const response = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
      const data = await response.json() as { memory?: MemoryRecord; error?: string };
      if (!response.ok) throw new Error(data.error || "记忆操作失败");
      if (method === "DELETE") setMemories((old) => id ? old.filter((item) => item.id !== id) : []);
      else if (data.memory) setMemories((old) => [data.memory!, ...old.filter((item) => item.id !== data.memory!.id)]);
      setEditing(null);
      setContent("");
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

  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>Memory 与隐私</h1>
    <p className={styles.intro}>记忆按用户和角色隔离。可查看、修改或清空；包含敏感信息的内容不会自动保存。</p>
    <section className={styles.section}><h2>角色记忆</h2>{error ? <p role="alert">{error}</p> : null}{roles.map((role) => <label className={styles.toggle} key={role.role_id}><span>{role.display_name}</span><input type="checkbox" checked={role.memory_enabled} disabled={saving === role.role_id} onChange={(event) => void updateRoleMemory(role, event.target.checked)} /></label>)}{!roles.length && !error ? <p>暂无可配置角色。</p> : null}</section>
    <section className={styles.section}><h2>已保存的记忆</h2><div className={styles.fields}>
      <label>角色<SelectMenu fullWidth value={String(selectedRoleId)} ariaLabel="角色" options={[...(roles.map((role) => ({ value: String(role.role_id), label: String(role.display_name) })))]} onChange={value => { setSelectedRoleId(value); setMemories([]); }} /></label>
      <label>类型<SelectMenu fullWidth value={String(kind)} ariaLabel="类型" options={[...(Object.entries(KIND_LABELS).map(([value, label]) => ({ value: String(value), label: String(label) })))]} onChange={value => setKind(value as MemoryKind)} /></label>
    </div>
    <div className={styles.memoryEditor}><input aria-label="记忆内容" value={content} maxLength={300} placeholder="添加一条记忆" onChange={(event) => setContent(event.target.value)} /><button type="button" disabled={busy || !content.trim() || !roles.find((role) => role.role_id === selectedRoleId)?.memory_enabled} onClick={() => void mutate(editing ? "PATCH" : "POST", editing ? { id: editing, content } : { kind, content })}>{editing ? "保存修改" : "添加记忆"}</button>{editing ? <button type="button" onClick={() => { setEditing(null); setContent(""); }}>取消</button> : null}</div>
    <div className={styles.memoryList}>{memories.map((memory) => <article key={memory.id}><div><small>{KIND_LABELS[memory.kind]}</small><p>{memory.content}</p></div><button type="button" disabled={busy} onClick={() => { setEditing(memory.id); setContent(memory.content); }}>编辑</button><button type="button" disabled={busy} onClick={() => void mutate("DELETE", undefined, memory.id)}>删除</button></article>)}{!memories.length ? <p>这个角色还没有保存的记忆。</p> : null}</div>
    {memories.length ? <button className={styles.clearButton} type="button" disabled={busy} onClick={() => { if (window.confirm("清空这个角色的全部记忆？此操作无法恢复。")) void mutate("DELETE"); }}>清空当前角色记忆</button> : null}
    </section>
  </div>;
}
