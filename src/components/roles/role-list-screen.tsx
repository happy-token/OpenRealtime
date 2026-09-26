"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, MessageCircle, Plus, Search, Settings2, Sparkles, Star, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createRole, deleteRole, fetchRoles } from "@/lib/role-catalog-client";
import { ROLE_MODE_LABELS, type RoleRecord } from "@/lib/role-records";
import { conversationHref } from "@/components/workspace/workspace-shell";
import { DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import styles from "./role-list-screen.module.css";

export function RoleListScreen() {
  const router = useRouter();
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [defaultRoleId, setDefaultRoleId] = useState("default-assistant");
  const [defaultError, setDefaultError] = useState("");
  const [savingDefault, setSavingDefault] = useState(false);
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [pendingDeleteRole, setPendingDeleteRole] = useState<RoleRecord | null>(null);
  const [deletingRoleId, setDeletingRoleId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const [creating, setCreating] = useState(false);

  async function createDraftRole() {
    if (creating) return;
    setCreating(true);
    setError("");
    try {
      const created = await createRole({
        displayName: "未命名角色",
        voiceProvider: "doubao",
        voiceId: DEFAULT_TTS_VOICE,
        voiceDialect: "",
        personaId: null,
        avatarId: null,
        enabledModes: ["conversation"],
        defaultMode: "conversation",
        defaultSelections: {},
        memoryEnabled: true,
        modelId: null,
        toolIds: [],
      });
      router.push(`/roles/${encodeURIComponent(created.role_id)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "角色创建失败");
      setCreating(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void fetchRoles(controller.signal).then((items) => {
      setRoles(items);
      setLoading(false);
    }).catch((cause) => {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : "角色列表读取失败");
      setLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!pendingDeleteRole) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deletingRoleId) setPendingDeleteRole(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [deletingRoleId, pendingDeleteRole]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/user/default-role", { cache: "no-store", signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<{ roleId: string }> : null)
      .then((payload) => { if (!controller.signal.aborted && payload?.roleId) setDefaultRoleId(payload.roleId); })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function setDefault(roleId: string) {
    if (savingDefault) return;
    setSavingDefault(true);
    setDefaultError("");
    try {
      const response = await fetch("/api/user/default-role", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roleId }),
      });
      const payload = await response.json() as { roleId?: string; error?: string };
      if (!response.ok || !payload.roleId) throw new Error(payload.error || "默认角色保存失败");
      setDefaultRoleId(payload.roleId);
    } catch (cause) {
      setDefaultError(cause instanceof Error ? cause.message : "默认角色保存失败");
    } finally {
      setSavingDefault(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDeleteRole || deletingRoleId) return;
    setDeletingRoleId(pendingDeleteRole.role_id);
    setDeleteError("");
    try {
      await deleteRole(pendingDeleteRole.role_id);
      setRoles((items) => items.filter((item) => item.role_id !== pendingDeleteRole.role_id));
      setSelectedRoleId((selected) => selected === pendingDeleteRole.role_id ? null : selected);
      setPendingDeleteRole(null);
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause.message : "角色删除失败");
    } finally {
      setDeletingRoleId(null);
    }
  }

  const visibleRoles = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? roles.filter((role) => (
      role.display_name.toLocaleLowerCase().includes(needle)
      || role.persona_name?.toLocaleLowerCase().includes(needle)
    )) : roles;
  }, [query, roles]);

  return <div className={styles.page}>
    <header className={styles.header}>
      <div className={styles.heading}>
        <h1>角色</h1>
        <p>选择一个角色开始对话，或进入详情调整声音、能力与呈现方式。</p>
      </div>
      <div className={styles.headerActions}>
        <label className={styles.search}>
          <Search />
          <span className="sr-only">搜索角色</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索角色或人设" />
        </label>
        <button className={`${styles.createButton} liquid-glass-button`} data-variant="primary" type="button" disabled={creating} onClick={() => void createDraftRole()}><Plus />{creating ? "正在创建…" : "新建角色"}</button>
      </div>
    </header>
    {error ? <div className={styles.state} role="alert"><strong>角色暂时不可用</strong><p>{error}</p></div> : null}
    {defaultError ? <div className={styles.state} role="alert"><strong>设置默认角色失败</strong><p>{defaultError}</p></div> : null}
    {deleteError ? <div className={styles.state} role="alert"><strong>删除角色失败</strong><p>{deleteError}</p></div> : null}
    {loading ? <div className={styles.loading} role="status" aria-label="正在加载角色">{[0,1,2,3].map((item) => <i key={item} />)}</div> : null}
    {!loading && !error ? <section className={styles.list} aria-label="角色列表">
      {visibleRoles.map((role) => <RoleCard
        key={role.role_id}
        role={role}
        isDefault={role.role_id === defaultRoleId}
        isSelected={role.role_id === selectedRoleId}
        savingDefault={savingDefault}
        onSelect={setSelectedRoleId}
        onSetDefault={setDefault}
        onRequestDelete={setPendingDeleteRole}
      />)}
      {!visibleRoles.length ? <div className={styles.state}><strong>没有匹配的角色</strong><p>换一个关键词，或创建新角色。</p></div> : null}
    </section> : null}
    {pendingDeleteRole ? <div className={styles.deleteBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingRoleId) setPendingDeleteRole(null); }}>
      <section className={styles.deleteDialog} role="alertdialog" aria-modal="true" aria-labelledby="delete-role-title" aria-describedby="delete-role-description">
        <header><span><Trash2 /></span><div><small>DELETE ROLE</small><h2 id="delete-role-title">删除这个角色？</h2></div><button type="button" aria-label="关闭删除角色确认" disabled={Boolean(deletingRoleId)} onClick={() => setPendingDeleteRole(null)}><X /></button></header>
        <p id="delete-role-description"><strong>{pendingDeleteRole.display_name}</strong>将从角色列表移除。数字人形象、人设和声音资源不会被删除。</p>
        <footer><button type="button" disabled={Boolean(deletingRoleId)} onClick={() => setPendingDeleteRole(null)}>取消</button><button type="button" data-danger="true" disabled={Boolean(deletingRoleId)} onClick={() => void confirmDelete()}><Trash2 />{deletingRoleId ? "正在删除…" : "确认删除"}</button></footer>
      </section>
    </div> : null}
  </div>;
}

function RoleCard({ role, isDefault, isSelected, savingDefault, onSelect, onSetDefault, onRequestDelete }: {
  role: RoleRecord;
  isDefault: boolean;
  isSelected: boolean;
  savingDefault: boolean;
  onSelect: (roleId: string) => void;
  onSetDefault: (roleId: string) => void;
  onRequestDelete: (role: RoleRecord) => void;
}) {
  const canDelete = role.role_id !== "default-assistant" && !isDefault;
  return <article className={`${styles.roleCard} liquid-glass-surface`} data-selected={isSelected}>
    <span className={styles.portrait}>
      {role.avatar_image_url ? <Image src={role.avatar_image_url} alt="" fill sizes="(max-width: 720px) 50vw, 280px" unoptimized /> : <><i /><Sparkles /></>}
    </span>
    <span className={styles.cardShade} aria-hidden="true" />
    <button
      className={styles.selectSurface}
      type="button"
      aria-label={`选择${role.display_name}`}
      aria-pressed={isSelected}
      onClick={() => onSelect(role.role_id)}
    />
    <div className={styles.roleCopy}>
      <strong>{role.display_name}</strong>
      <small>{role.persona_name ?? "通用助手"}</small>
    </div>
    {isDefault ? <span className={styles.defaultBadge}><Star fill="currentColor" />默认角色</span>
      : <button className={styles.defaultButton} type="button" disabled={savingDefault} onClick={() => onSetDefault(role.role_id)} aria-label={`将${role.display_name}设为默认角色`}><Star />设为默认</button>}
    {isSelected ? <span className={styles.selectedBadge}><Check /><span>已选中</span></span> : null}
    <div className={styles.cardActions}>
      <Link className={`${styles.startButton} liquid-glass-button`} data-variant="primary" href={conversationHref(role, role.default_mode)} aria-label={`使用${role.display_name}开始对话`} title={`使用默认方式：${ROLE_MODE_LABELS[role.default_mode]}`}><MessageCircle />对话</Link>
      <Link className={styles.detailButton} href={`/roles/${encodeURIComponent(role.role_id)}`} aria-label={`查看${role.display_name}详情`}><Settings2 />详情</Link>
      {canDelete ? <button className={styles.deleteButton} type="button" aria-label={`删除角色${role.display_name}`} title="删除角色" onClick={() => onRequestDelete(role)}><Trash2 /></button> : null}
    </div>
  </article>;
}
