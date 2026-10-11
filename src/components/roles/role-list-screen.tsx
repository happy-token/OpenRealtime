"use client";

import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, MessageCircle, Plus, Search, Settings2, Sparkles, Star, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createRole, deleteRole, fetchRoles, RoleCreationError } from "@/lib/role-catalog-client";
import { accountLoginHref } from "@/hooks/use-current-user";
import { isProtectedBuiltinRole, ROLE_MODE_LABELS, type RoleRecord } from "@/lib/role-records";
import { conversationHref } from "@/components/workspace/workspace-shell";
import { BAILIAN_TTS_VOICE_OPTIONS, DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import { selectedDefaultTtsProvider, type ProviderVoiceCatalog } from "@/lib/default-role-voice";
import styles from "./role-list-screen.module.css";

export function RoleListScreen() {
  const { t } = useLanguage();
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
  const [creationError, setCreationError] = useState("");
  const [creationNeedsLogin, setCreationNeedsLogin] = useState(false);

  async function createDraftRole() {
    if (creating) return;
    setCreating(true);
    setCreationError("");
    setCreationNeedsLogin(false);
    try {
      // A draft can be created before voice services are configured or accessible.
      const catalog = await fetch("/api/provider-instances", { cache: "no-store" })
        .then(response => response.ok ? response.json() as Promise<ProviderVoiceCatalog> : null)
        .catch(() => null);
      const selectedProvider = catalog ? selectedDefaultTtsProvider(catalog) : null;
      const voiceProvider = selectedProvider === "dashscope" ? "bailian" : "doubao";
      const created = await createRole({
        displayName: "未命名角色",
        voiceProvider,
        voiceId: voiceProvider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS[0].value : DEFAULT_TTS_VOICE,
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
      router.push(`/roles/${encodeURIComponent(created.role_id)}?settings=1`);
    } catch (cause) {
      setCreationError(cause instanceof Error ? cause.message : "角色创建失败");
      setCreationNeedsLogin(cause instanceof RoleCreationError && cause.status === 401);
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
    const availableRoles = roles.filter((role) => role.role_id !== "default-assistant");
    return needle ? availableRoles.filter((role) => (
      role.display_name.toLocaleLowerCase().includes(needle)
      || t(role.display_name).toLocaleLowerCase().includes(needle)
      || role.persona_name?.toLocaleLowerCase().includes(needle)
    )) : availableRoles;
  }, [query, roles, t]);

  return <div className={styles.page}>
    <header className={styles.header}>
      <div className={styles.heading}>
        <h1>{t("角色")}</h1>
        <p>{t("选择一个角色开始对话，或进入详情调整声音、能力与呈现方式。")}</p>
      </div>
      <div className={styles.headerActions}>
        <label className={styles.search}>
          <Search />
          <span className="sr-only">{t("搜索角色")}</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("搜索角色或人设")} />
        </label>
        <button className={`${styles.createButton} liquid-glass-button`} data-variant="primary" type="button" disabled={creating} onClick={() => void createDraftRole()}><Plus />{creating ? t("正在创建…") : t("新建角色")}</button>
      </div>
    </header>
    {error ? <div className={styles.state} role="alert"><strong>{t("角色暂时不可用")}</strong><p>{t(error)}</p></div> : null}
    {creationError ? <div className={styles.state} role="alert"><strong>{t("角色创建失败")}</strong><p>{creationError}</p>{creationNeedsLogin ? <Link href={accountLoginHref("/roles")}>{t("登录后创建")}</Link> : null}</div> : null}
    {defaultError ? <div className={styles.state} role="alert"><strong>{t("设置默认角色失败")}</strong><p>{defaultError}</p></div> : null}
    {deleteError ? <div className={styles.state} role="alert"><strong>{t("删除角色失败")}</strong><p>{deleteError}</p></div> : null}
    {loading ? <div className={styles.loading} role="status" aria-label={t("正在加载角色")}>{[0,1,2,3].map((item) => <i key={item} />)}</div> : null}
    {!loading && !error ? <section className={styles.list} aria-label={t("角色列表")}>
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
      {!visibleRoles.length ? <div className={styles.state}><strong>{t("没有匹配的角色")}</strong><p>{t("换一个关键词，或创建新角色。")}</p></div> : null}
    </section> : null}
    {pendingDeleteRole ? <div className={styles.deleteBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingRoleId) setPendingDeleteRole(null); }}>
      <section className={styles.deleteDialog} role="alertdialog" aria-modal="true" aria-labelledby="delete-role-title" aria-describedby="delete-role-description">
        <header><span><Trash2 /></span><div><h2 id="delete-role-title">{t("删除这个角色？")}</h2></div><button type="button" aria-label={t("关闭删除角色确认")} disabled={Boolean(deletingRoleId)} onClick={() => setPendingDeleteRole(null)}><X /></button></header>
        <p id="delete-role-description"><strong>{t(pendingDeleteRole.display_name)}</strong>{t("将从角色列表移除。数字人形象、人设和声音资源不会被删除。")}</p>
        <footer><button type="button" disabled={Boolean(deletingRoleId)} onClick={() => setPendingDeleteRole(null)}>{t("取消")}</button><button type="button" data-danger="true" disabled={Boolean(deletingRoleId)} onClick={() => void confirmDelete()}><Trash2 />{deletingRoleId ? t("正在删除…") : t("确认删除")}</button></footer>
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
  const { t } = useLanguage();
  const canDelete = !isProtectedBuiltinRole(role.role_id) && !isDefault;
  return <article className={`${styles.roleCard} liquid-glass-surface`} data-selected={isSelected}>
    <span className={styles.portrait}>
      {role.avatar_image_url ? <Image src={role.avatar_image_url} alt="" fill sizes="(max-width: 720px) 50vw, 280px" unoptimized /> : <><i /><Sparkles /></>}
    </span>
    <span className={styles.cardShade} aria-hidden="true" />
    <button
      className={styles.selectSurface}
      type="button"
      aria-label={t("选择{name}", { name: t(role.display_name) })}
      aria-pressed={isSelected}
      onClick={() => onSelect(role.role_id)}
    />
    <div className={styles.roleCopy}>
      <strong>{t(role.display_name)}</strong>
      <small>{t(role.persona_name ?? "通用助手")}</small>
    </div>
    {isDefault ? <span className={styles.defaultBadge}><Star fill="currentColor" />{t("默认角色")}</span>
      : <button className={styles.defaultButton} type="button" disabled={savingDefault} onClick={() => onSetDefault(role.role_id)} aria-label={t("将 {name} 设为默认角色", { name: t(role.display_name) })}><Star />{t("设为默认")}</button>}
    {isSelected ? <span className={styles.selectedBadge}><Check /><span>{t("已选中")}</span></span> : null}
    <div className={styles.cardActions}>
      <Link className={`${styles.startButton} liquid-glass-button`} data-variant="primary" href={conversationHref(role, role.default_mode)} aria-label={t("与 {name} 对话", { name: t(role.display_name) })} title={t("使用默认方式：") + (t(ROLE_MODE_LABELS[role.default_mode])) + ""}><MessageCircle />{t("对话")}</Link>
      <Link className={styles.detailButton} href={`/roles/${encodeURIComponent(role.role_id)}`} aria-label={t("查看 {name} 详情", { name: t(role.display_name) })}><Settings2 />{t("详情")}</Link>
      {canDelete ? <button className={styles.deleteButton} type="button" aria-label={t("删除角色") + (t(role.display_name)) + ""} title={t("删除角色")} onClick={() => onRequestDelete(role)}><Trash2 /></button> : null}
    </div>
  </article>;
}
