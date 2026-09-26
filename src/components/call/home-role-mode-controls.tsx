"use client";

import Image from "next/image";
import Link from "next/link";
import { Check, ChevronDown, ChevronUp, MessageCircle, Plus, Star, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type TouchEvent } from "react";
import type { AvatarDisplayConfig, ExperienceMode } from "@/components/digital-human/types";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { fetchRoles, saveRole } from "@/lib/role-catalog-client";
import { resolveRoleDefaultSelection, ROLE_MODE_LABELS, type RolePresentationMode, type RoleRecord } from "@/lib/role-records";
import type { VoiceVisualTheme } from "./voice-theme";
import { conversationHref } from "@/components/workspace/workspace-shell";
import { saveRoleStartIntent } from "@/lib/role-start-intent";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";
import { WorkbenchActionFolder, WorkbenchConversationOption, WorkbenchRealtimeOption } from "@/components/workspace/workbench-resource-rails";
import { usePersonalLipsyncReady } from "@/hooks/use-personal-lipsync-ready";
import styles from "./home-role-mode-controls.module.css";

type Panel = "roles" | "modes" | null;

interface Props {
  role: RoleRecord;
  mode: RolePresentationMode;
  avatar: OwnedAvatarRecord | null;
  config: AvatarDisplayConfig;
  canStart: boolean;
  visualTheme: VoiceVisualTheme;
  themes: readonly { id: VoiceVisualTheme; name: string; colors: readonly string[] }[];
  onVisualThemeChange: (theme: VoiceVisualTheme) => void;
  onRoleSelect?: (role: RoleRecord) => void;
  onModeSelect: (mode: RolePresentationMode, actionId?: string, talkingVariantId?: string) => Promise<void>;
  onStart: (mode?: ExperienceMode) => void;
  showRoleSelector?: boolean;
  runtimeLipSyncAvailable: boolean;
}

export function HomeRoleModeControls({ role, mode, avatar, config, canStart, visualTheme, themes, onVisualThemeChange, onRoleSelect, onModeSelect, onStart, showRoleSelector = true, runtimeLipSyncAvailable }: Props) {
  const [panel, setPanel] = useState<Panel>(null);
  const [roles, setRoles] = useState<RoleRecord[]>([role]);
  const [currentRole, setCurrentRole] = useState(role);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [savingDefault, setSavingDefault] = useState(false);
  const [expandedActionId, setExpandedActionId] = useState<string | null>(null);
  const personalLipsyncReady = usePersonalLipsyncReady();
  const touchStartY = useRef<number | null>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  function cancelPanelTimers() {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  }

  function openPanel(nextPanel: Exclude<Panel, null>, delayed = false) {
    cancelPanelTimers();
    const show = () => setPanel(nextPanel);
    if (delayed) openTimer.current = window.setTimeout(show, 150);
    else show();
  }

  function togglePanel(nextPanel: Exclude<Panel, null>) {
    cancelPanelTimers();
    setPanel((current) => current === nextPanel ? null : nextPanel);
  }

  function schedulePanelClose() {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    openTimer.current = null;
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setPanel(null), 350);
  }

  useEffect(() => () => cancelPanelTimers(), []);

  useEffect(() => {
    setCurrentRole(role);
    if (!showRoleSelector) {
      setRoles([role]);
      return;
    }
    const controller = new AbortController();
    void fetchRoles(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setRoles(items.some((item) => item.role_id === role.role_id) ? items : [role, ...items]);
      setCurrentRole(items.find((item) => item.role_id === role.role_id) ?? role);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [role, showRoleSelector]);

  useEffect(() => {
    if (!panel) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setPanel(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [panel]);

  const actions = useMemo(() => avatar?.actions.filter((action) => !action.deleted_at && action.video_url) ?? [], [avatar]);
  const talkingMaterials = useMemo(() => actions.flatMap((action) => (action.talking_variants ?? [])
    .filter((variant) => !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url)
    .map((variant) => ({ action, variant }))), [actions]);
  const remembered = currentRole.default_selections?.[mode as "motion" | "offline" | "lip-sync"];
  const fallback = resolveRoleDefaultSelection(avatar, mode, remembered);
  const selectedActionId = config.segmentedAvatarId === currentRole.avatar_id && mode !== "conversation" && mode !== "realtime"
    ? config.segmentedAvatarActionId : fallback?.action_id;
  const selectedVariantId = config.segmentedAvatarId === currentRole.avatar_id && mode === "offline"
    ? config.motionTalkingVariantId : fallback?.talking_variant_id;
  const selectedMaterial = talkingMaterials.find(({ action, variant }) => action.avatar_action_id === selectedActionId && variant.id === selectedVariantId);
  const selectedAction = actions.find((action) => action.avatar_action_id === selectedActionId);
  const selectionLabel = mode === "offline" ? selectedMaterial?.variant.display_name ?? "选择口型对齐"
    : mode === "lip-sync" || mode === "motion" ? selectedAction?.display_name ?? "选择动作"
      : mode === "realtime" ? "角色数字人" : "Orb";
  const assetModes = mode === "offline" || mode === "lip-sync" || mode === "motion";
  const canSetDefault = !savingDefault && !pending && (mode === "conversation" || mode === "realtime" || Boolean(selectedActionId && (mode !== "offline" || selectedVariantId)));
  const isCurrentSelectionDefault = currentRole.default_mode === mode && (!assetModes || Boolean(fallback
    && selectedActionId === fallback.action_id
    && (mode !== "offline" || selectedVariantId === fallback.talking_variant_id)));

  async function selectMode(nextMode: RolePresentationMode, actionId?: string, talkingVariantId?: string) {
    if (pending) return;
    if (nextMode === "lip-sync" && !personalLipsyncReady) { setError("请先在设置中配置并测试个人口型对齐服务"); return; }
    const preferred = currentRole.default_selections?.[nextMode as "motion" | "offline" | "lip-sync"];
    const fallbackSelection = resolveRoleDefaultSelection(avatar, nextMode, preferred);
    setPending(true);
    setError("");
    try {
      await onModeSelect(nextMode, actionId ?? fallbackSelection?.action_id, talkingVariantId ?? (actionId ? undefined : fallbackSelection?.talking_variant_id));
      if (nextMode === "conversation" || nextMode === "realtime") setPanel(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模式切换失败");
    } finally {
      setPending(false);
    }
  }

  async function setCurrentAsDefault() {
    if (!canSetDefault) return;
    setSavingDefault(true);
    setError("");
    try {
      const defaultSelections = { ...(currentRole.default_selections ?? {}) };
      if (assetModes && selectedActionId) defaultSelections[mode] = {
        action_id: selectedActionId,
        ...(mode === "offline" && selectedVariantId ? { talking_variant_id: selectedVariantId } : {}),
      };
      const saved = await saveRole(currentRole.role_id, {
        displayName: currentRole.display_name,
        voiceProvider: currentRole.voice_provider,
        voiceId: currentRole.voice_id,
        voiceDialect: currentRole.voice_dialect ?? "",
        personaId: currentRole.persona_id,
        avatarId: currentRole.avatar_id,
        enabledModes: currentRole.enabled_modes,
        defaultMode: mode,
        defaultSelections,
        memoryEnabled: currentRole.memory_enabled,
        modelId: currentRole.model_id ?? null,
        toolIds: currentRole.tool_ids,
      });
      setCurrentRole(saved);
      setRoles((items) => items.map((item) => item.role_id === saved.role_id ? saved : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "默认选择保存失败");
    } finally {
      setSavingDefault(false);
    }
  }

  function onTouchStart(event: TouchEvent<HTMLElement>) { touchStartY.current = event.touches[0]?.clientY ?? null; }
  function onTouchEnd(event: TouchEvent<HTMLElement>) {
    const distance = touchStartY.current === null ? 0 : (event.changedTouches[0]?.clientY ?? 0) - touchStartY.current;
    touchStartY.current = null;
    if (distance > 85) setPanel(null);
  }

  return <div className={styles.controls} data-open={panel ?? "none"}>
    {showRoleSelector ? <button className={styles.rightHandle} type="button" aria-label="打开角色列表" aria-expanded={panel === "roles"} onPointerEnter={() => openPanel("roles", true)} onPointerLeave={schedulePanelClose} onFocus={() => openPanel("roles")} onClick={() => togglePanel("roles")}><span /></button> : null}
    {showRoleSelector ? <button className={styles.mobileRoleButton} type="button" aria-label={`选择角色，当前${currentRole.display_name}`} aria-expanded={panel === "roles"} onClick={() => setPanel(panel === "roles" ? null : "roles")}>
      <RolePortrait role={currentRole} /><strong>{currentRole.display_name}</strong><ChevronDown />
    </button> : null}
    <button className={styles.bottomHandle} type="button" aria-label={`选择呈现方式，当前${ROLE_MODE_LABELS[mode]}，${selectionLabel}`} aria-expanded={panel === "modes"} onPointerEnter={() => openPanel("modes", true)} onPointerLeave={schedulePanelClose} onFocus={() => openPanel("modes")} onClick={() => togglePanel("modes")}>
      <span className={styles.handleLine} /><span className={styles.handleSummary}>{ROLE_MODE_LABELS[mode]} · {selectionLabel}</span><ChevronUp />
    </button>
    {panel ? <button className={styles.backdrop} type="button" aria-label="关闭选择面板" onPointerEnter={schedulePanelClose} onClick={() => setPanel(null)} /> : null}

    {showRoleSelector ? <aside className={styles.rolePanel} data-open={panel === "roles"} aria-label="角色列表" aria-hidden={panel !== "roles"} inert={panel !== "roles"} onPointerEnter={cancelPanelTimers} onPointerLeave={schedulePanelClose}>
      <div className={styles.roleList}>
        {roles.map((item) => <div key={item.role_id} className={styles.roleCard} data-selected={item.role_id === currentRole.role_id} data-default={item.role_id === currentRole.role_id && isCurrentSelectionDefault}>
          <button className={styles.roleSelectButton} type="button" aria-label={`选择角色：${item.display_name}，默认${ROLE_MODE_LABELS[item.default_mode]}`} onClick={() => { if (item.role_id !== currentRole.role_id) { setCurrentRole(item); setPanel(null); onRoleSelect?.(item); } else setPanel(null); }}>
            <span className={styles.roleArtwork}>{item.avatar_image_url ? <Image src={item.avatar_image_url} alt="" fill sizes="(max-width: 760px) 160px, 130px" unoptimized /> : <UserRound />}</span>
            <span className={styles.roleCardCopy}><strong>{item.display_name}</strong><small>{item.persona_name ? `${item.persona_name} · ` : ""}默认：{ROLE_MODE_LABELS[item.default_mode]}{item.role_id === currentRole.role_id && item.default_mode === mode && assetModes ? ` · ${selectionLabel}` : ""}</small></span>
            {item.role_id === currentRole.role_id && isCurrentSelectionDefault ? <span className={styles.roleDefaultBadge}><Star fill="currentColor" />默认</span> : null}
            {item.role_id === currentRole.role_id ? <Check className={styles.roleSelectedCheck} /> : null}
          </button>
          <button className={`${styles.roleStartButton} liquid-glass-button`} data-variant="primary" type="button" disabled={item.role_id === currentRole.role_id && !canStart} aria-label={`与${item.display_name}开始对话`} onClick={() => {
            if (item.role_id === currentRole.role_id) {
              onStart(mode === "conversation" ? "voice" : "avatar");
              return;
            }
            saveRoleStartIntent(item.role_id);
            window.location.assign(conversationHref(item, item.default_mode));
          }}><MessageCircle />对话</button>
          {item.role_id === currentRole.role_id && !isCurrentSelectionDefault ? <button className={styles.roleDefaultButton} type="button" disabled={!canSetDefault} title={mode === "offline" ? "设当前方式与口型对齐为默认" : mode === "lip-sync" || mode === "motion" ? "设当前方式与动作为默认" : "设当前方式为默认"} onClick={() => void setCurrentAsDefault()}><Star />{savingDefault ? "保存中" : "设为默认"}</button> : null}
        </div>)}
        <Link className={styles.addRoleCard} href="/roles/new" aria-label="新建角色"><Plus /><span>新建角色</span></Link>
      </div>
    </aside> : null}

    <aside className={styles.modePanel} data-open={panel === "modes"} aria-label="模式与素材" aria-hidden={panel !== "modes"} inert={panel !== "modes"} onPointerEnter={cancelPanelTimers} onPointerLeave={schedulePanelClose}>
      <header onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}><div><small>MODE</small><strong>{currentRole.display_name} · {ROLE_MODE_LABELS[mode]}</strong></div><button type="button" aria-label="关闭模式选择" onClick={() => setPanel(null)}><X /></button></header>
      <div className={styles.materialList} data-kind="action">
        {currentRole.enabled_modes.includes("conversation") ? <WorkbenchConversationOption selected={mode === "conversation"} onSelect={() => void selectMode("conversation")} /> : null}
        {actions.map((action, index) => {
          const variants = currentRole.enabled_modes.includes("offline") ? (action.talking_variants ?? []).filter((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url) : [];
          return <WorkbenchActionFolder key={action.avatar_action_id}
            action={{ avatarActionId: action.avatar_action_id, displayName: action.display_name, videoUrl: action.video_url, state: "available", pendingModelCount: 0 }}
            index={index} image={avatar?.source_image_url ?? undefined} variants={variants}
            selected={mode !== "conversation" && mode !== "realtime" && selectedActionId === action.avatar_action_id}
            selectedVariantId={selectedVariantId} open={expandedActionId === action.avatar_action_id}
            onOpenChange={(open) => setExpandedActionId(open ? action.avatar_action_id : null)}
            onSelectRuntime={personalLipsyncReady && runtimeLipSyncAvailable && currentRole.enabled_modes.includes("lip-sync") ? () => void selectMode("lip-sync", action.avatar_action_id) : undefined}
            runtimeSelected={mode === "lip-sync" && selectedActionId === action.avatar_action_id}
            onSelectVariant={(variantId) => void selectMode("offline", action.avatar_action_id, variantId)}
            onCreateTalking={() => window.location.assign(avatarResourceHref({ task: "talking", avatarId: avatar?.avatar_id, actionId: action.avatar_action_id, returnTo: currentRole.role_id }))}
          />;
        })}
        {currentRole.enabled_modes.includes("realtime") ? <WorkbenchRealtimeOption selected={mode === "realtime"} onSelect={() => void selectMode("realtime")} /> : null}
        {mode === "conversation" ? themes.map((theme) => <button className={styles.themeCard} type="button" key={theme.id} data-selected={visualTheme === theme.id} aria-pressed={visualTheme === theme.id} onClick={() => onVisualThemeChange(theme.id)}><span style={{ background: `linear-gradient(135deg, ${theme.colors.join(",")})` }} /><strong>{theme.name}</strong></button>) : null}
        {actions.length === 0 ? <p className={styles.empty}>当前角色还没有可用动作</p> : null}
      </div>
      <footer><span>{ROLE_MODE_LABELS[mode]} · {selectionLabel}</span><button type="button" disabled={!canStart || pending || (mode === "lip-sync" && !personalLipsyncReady)} onClick={() => onStart(mode === "conversation" ? "voice" : "avatar")}>开始对话</button></footer>
    </aside>
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
  </div>;
}

function RolePortrait({ role }: { role: RoleRecord }) {
  return <span className={styles.portrait}>{role.avatar_image_url ? <Image src={role.avatar_image_url} alt="" fill sizes="64px" unoptimized /> : <UserRound />}</span>;
}
