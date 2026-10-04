"use client";
import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";
import { SelectMenu } from "@/components/ui/select-menu";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, Check, ChevronDown, ChevronRight, Film, GripHorizontal, LoaderCircle, MessageCircle, Pencil, Plus, Radio, Settings2, Sparkles, Star, UserRound, Volume2, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { HomeRoleModeControls } from "@/components/call/home-role-mode-controls";
import { PreviewVideo } from "@/components/workspace/workbench-resource-rails";
import homePreviewStyles from "@/components/call/preview-workspace-lab.module.css";
import { VOICE_VISUAL_THEME_OPTIONS, type VoiceVisualTheme } from "@/components/call/voice-theme";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { TTS_PROVIDER_OPTIONS } from "@/components/drawer/voice-options";
import { PROVIDER_CATALOG } from "@/lib/provider-catalog";
import { describeVoiceSelection, VoiceSelector } from "@/components/voice/voice-selector";
import { conversationHref } from "@/components/workspace/workspace-shell";
import type { PersonaSummary } from "@/lib/avatar-persona";
import { fetchOwnedAvatars, fetchPersonalAvatars } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import { readJsonResponse } from "@/lib/http-json-response";
import { saveHostedAvatarProfile } from "@/lib/hosted-avatar-profile";
import { fetchRole, saveRole } from "@/lib/role-catalog-client";
import { readRoleActionPreferences, rememberRoleActionSelection } from "@/lib/role-action-preferences";
import { enabledRoleModesForAvatar, preferredRoleMode, roleDetailDisplayMode, ROLE_MODE_LABELS, ROLE_PRESENTATION_MODES, type RolePresentationMode, type RoleRecord } from "@/lib/role-records";
import { fetchTools } from "@/lib/tool-catalog-client";
import type { ToolRecord } from "@/lib/tool-records";
import type { KnowledgeDocument } from "@/lib/knowledge-catalog-repository";
import { VoiceStartButton } from "@/components/ui/voice-start-button";
import styles from "./role-detail-screen.module.css";
import { AssetCard, DeletedAssets, applyAssetChange, useRoleAssetManagement, type AssetChange } from "./role-asset-management";
import { cleanRoleAssetDefaults, validRoleAssetSelection } from "@/lib/role-asset-selections";
import { AvatarChoiceGrid } from "./avatar-choice-grid";
import { PersonaChoiceGrid } from "./persona-choice-grid";
import { announceNavigationStart } from "@/components/navigation/navigation-events";
import { AvatarProductionOverlay } from "@/components/avatar/avatar-production-overlay";
import { AvatarUploadDialog } from "@/components/avatar/avatar-upload-dialog";
import type { AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";
import { useAvatarCapabilities } from "@/hooks/use-avatar-capabilities";
import { usePersonalLipsyncReady } from "@/hooks/use-personal-lipsync-ready";
import { useOfficialRealtimeAvatars } from "@/hooks/use-official-realtime-avatars";

type ConfigModule = "voice" | "persona" | "tools" | "knowledge" | null;
type ConfigSection = "foundation" | "presentation" | "avatar" | "realtime" | "action" | "talking" | null;
type DetailPanel = "config" | null;

function roleSaveFingerprint(role: RoleRecord, knowledgeIds: string[]) {
  return JSON.stringify({
    displayName: role.display_name,
    voiceProvider: role.voice_provider,
    voiceId: role.voice_id,
    voiceDialect: role.voice_dialect ?? "",
    asrProvider: role.asr_provider ?? null,
    llmProvider: role.llm_provider ?? null,
    personaId: role.persona_id,
    avatarId: role.avatar_id,
    enabledModes: role.enabled_modes,
    defaultMode: role.default_mode,
    defaultSelections: role.default_selections,
    memoryEnabled: role.memory_enabled,
    modelId: role.model_id ?? null,
    toolIds: role.tool_ids,
    knowledgeIds,
  });
}

async function persistRoleDraft(role: RoleRecord, knowledgeIds: string[]) {
  const updated = await saveRole(role.role_id, {
    displayName: role.display_name,
    voiceProvider: role.voice_provider,
    voiceId: role.voice_id,
    voiceDialect: role.voice_dialect ?? "",
    asrProvider: role.asr_provider ?? null,
    llmProvider: role.llm_provider ?? null,
    personaId: role.persona_id,
    avatarId: role.avatar_id,
    enabledModes: role.enabled_modes,
    defaultMode: role.default_mode,
    defaultSelections: role.default_selections,
    memoryEnabled: role.memory_enabled,
    modelId: role.model_id ?? null,
    toolIds: role.tool_ids,
  });
  const response = await fetch(`/api/knowledge/bindings/${encodeURIComponent(role.role_id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ documentIds: knowledgeIds }),
  });
  const binding = await readJsonResponse<{ documentIds?: string[]; error?: string }>(response, "知识库绑定失败");
  if (!response.ok || !binding.documentIds) throw new Error(binding.error || "知识库绑定失败（其他角色配置已保存）");
  return { updated, knowledgeIds: binding.documentIds };
}

export function RoleDetailScreen({ roleId, initialSettingsOpen = false }: { roleId: string; initialSettingsOpen?: boolean }) {
  const { t } = useLanguage();
  const router = useRouter();
  const { capabilities } = useAvatarCapabilities();
  const personalLipsyncReady = usePersonalLipsyncReady();
  const [realtimeCatalogRevision, setRealtimeCatalogRevision] = useState(0);
  const { avatars: officialRealtimeAvatars, personalAvatars: personalRealtimeAvatars, configured: realtimeConfigured } = useOfficialRealtimeAvatars(true, realtimeCatalogRevision);
  const [role, setRole] = useState<RoleRecord | null>(null);
  const [avatar, setAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [avatars, setAvatars] = useState<OwnedAvatarRecord[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [tools, setTools] = useState<ToolRecord[]>([]);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeMode, setActiveMode] = useState<RolePresentationMode>("conversation");
  const [activeActionId, setActiveActionId] = useState<string | null>(null);
  const [activeTalkingVariantId, setActiveTalkingVariantId] = useState<string | null>(null);
  const [previewKind, setPreviewKind] = useState<"motion" | "talking">("motion");
  const [selectedRealtimeAvatarId, setSelectedRealtimeAvatarId] = useState<string | null>(null);
  const [visualTheme, setVisualTheme] = useState<VoiceVisualTheme>("cloud");
  const [defaultRoleId, setDefaultRoleId] = useState("");
  const [settingDefault, setSettingDefault] = useState(false);
  const [defaultError, setDefaultError] = useState("");
  const [openModule, setOpenModule] = useState<ConfigModule>(null);
  const [openSection, setOpenSection] = useState<ConfigSection>("foundation");
  const [openPanel, setOpenPanel] = useState<DetailPanel>(initialSettingsOpen ? "config" : null);
  const [configPosition, setConfigPosition] = useState({ x: 0, y: 0 });
  const [configWidth, setConfigWidth] = useState(480);
  const [draggingConfig, setDraggingConfig] = useState(false);
  const [resizingConfig, setResizingConfig] = useState(false);
  const [editingRoleName, setEditingRoleName] = useState(false);
  const [productionTask, setProductionTask] = useState<AvatarWorkbenchTask | null>(null);
  const [creatingRealtimeAvatar, setCreatingRealtimeAvatar] = useState(false);
  const [resourceRevision, setResourceRevision] = useState(0);
  const configPanelRef = useRef<HTMLElement | null>(null);
  const autoSaveTimerRef = useRef<number | null>(null);
  const lastSavedFingerprintRef = useRef("");
  const lastSavedAvatarIdRef = useRef<string | null>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number; minX: number; maxX: number; minY: number; maxY: number } | null>(null);
  const resizeRef = useRef<{ pointerId: number; startX: number; originWidth: number; maxWidth: number } | null>(null);

  useEffect(() => {
    const creationNotice = window.sessionStorage.getItem("openrealtime:role-create-notice");
    if (!creationNotice) return;
    window.sessionStorage.removeItem("openrealtime:role-create-notice");
    setNotice(creationNotice);
  }, []);

  useEffect(() => {
    if (!openPanel) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpenPanel(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [openPanel]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/user/default-role", { cache: "no-store", signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<{ roleId?: string }> : null)
      .then((data) => { if (!controller.signal.aborted) setDefaultRoleId(data?.roleId ?? ""); })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetchRole(roleId, controller.signal),
      Promise.all([fetchPersonalAvatars(controller.signal), fetchOwnedAvatars(controller.signal).catch(() => [])])
        .then(([personal, shared]) => [...personal, ...shared]),
      fetch("/api/personas", { cache: "no-store", signal: controller.signal })
        .then((response) => response.ok ? readJsonResponse<{ personas?: PersonaSummary[] }>(response, "人设列表读取失败") : { personas: [] }),
      fetchTools(controller.signal).catch(() => []),
      fetch(`/api/knowledge?roleId=${encodeURIComponent(roleId)}`, { cache: "no-store", signal: controller.signal }).then((response) => readJsonResponse<{ documents?: KnowledgeDocument[]; error?: string }>(response, "知识库读取失败")),
      fetch(`/api/knowledge/bindings/${encodeURIComponent(roleId)}`, { cache: "no-store", signal: controller.signal }).then((response) => readJsonResponse<{ documentIds?: string[]; error?: string }>(response, "知识库绑定读取失败")),
    ]).then(([nextRole, avatarRecords, personaPayload, toolRecords, knowledgePayload, bindingPayload]) => {
      if (!nextRole) throw new Error("角色不存在");
      const availableAvatars = avatarRecords.filter((item) => !item.deleted_at);
      const loadedPersonas = personaPayload.personas ?? [];
      const loadedTools = toolRecords.filter((tool) => tool.enabled);
      const loadedKnowledge = knowledgePayload.documents ?? [];
      const snapshotKey = `openrealtime-role-resource-return:${roleId}`;
      let selectedRole = nextRole;
      let selectedKnowledgeIds = bindingPayload.documentIds ?? [];
      lastSavedFingerprintRef.current = roleSaveFingerprint(nextRole, selectedKnowledgeIds);
      lastSavedAvatarIdRef.current = nextRole.avatar_id;
      let returnedActionId: string | null = null;
      try {
        const snapshot = JSON.parse(window.sessionStorage.getItem(snapshotKey) ?? "null") as {
          avatars?: string[]; personas?: string[]; tools?: string[]; knowledge?: string[]; actions?: string[]; variants?: string[];
          enabledModes?: RolePresentationMode[]; defaultMode?: RolePresentationMode;
        } | null;
        if (snapshot) {
          const addedAvatar = availableAvatars.find((item) => !snapshot.avatars?.includes(item.avatar_id));
          const addedPersona = loadedPersonas.find((item) => !snapshot.personas?.includes(item.personaId));
          const addedTool = loadedTools.find((item) => !snapshot.tools?.includes(item.tool_id));
          const addedKnowledge = loadedKnowledge.find((item) => !snapshot.knowledge?.includes(item.document_id));
          if (addedAvatar) selectedRole = { ...selectedRole, avatar_id: addedAvatar.avatar_id, avatar_image_url: addedAvatar.source_image_url, enabled_modes: enabledRoleModesForAvatar(selectedRole.enabled_modes, addedAvatar) };
          if (addedPersona) selectedRole = { ...selectedRole, persona_id: addedPersona.personaId, persona_name: addedPersona.personaName };
          if (addedTool) selectedRole = { ...selectedRole, tool_ids: [...new Set([...selectedRole.tool_ids, addedTool.tool_id])] };
          if (addedKnowledge) selectedKnowledgeIds = [...new Set([...selectedKnowledgeIds, addedKnowledge.document_id])];
          const selectedAvatar = availableAvatars.find((item) => item.avatar_id === selectedRole.avatar_id);
          const addedAction = selectedAvatar?.actions.find((item) => !item.deleted_at && !snapshot.actions?.includes(item.avatar_action_id));
          const addedVariant = selectedAvatar?.actions.flatMap((action) => (action.talking_variants ?? [])
            .filter((item) => item.method === "lipforcing" && !item.deleted_at && !snapshot.variants?.includes(item.id))
            .map((item) => ({ action, variant: item })))[0];
          if (addedAction) selectedRole = { ...selectedRole, enabled_modes: enabledRoleModesForAvatar(selectedRole.enabled_modes, selectedAvatar ?? null), default_selections: {
            ...selectedRole.default_selections, motion: { action_id: addedAction.avatar_action_id }, "lip-sync": { action_id: addedAction.avatar_action_id },
          } };
          if (addedAction) returnedActionId = addedAction.avatar_action_id;
          if (addedVariant) selectedRole = { ...selectedRole, enabled_modes: enabledRoleModesForAvatar(selectedRole.enabled_modes, selectedAvatar ?? null), default_selections: {
            ...selectedRole.default_selections, offline: { action_id: addedVariant.action.avatar_action_id, talking_variant_id: addedVariant.variant.id },
          } };
          if (addedVariant) returnedActionId = addedVariant.action.avatar_action_id;
          const pendingModes = snapshot.enabledModes?.filter((mode) => mode !== "motion" && ROLE_PRESENTATION_MODES.includes(mode)) ?? [];
          const restoredModes = pendingModes.length ? pendingModes : null;
          const restoredPendingMode = Boolean(restoredModes?.some((mode) => !selectedRole.enabled_modes.includes(mode)));
          if (restoredModes) selectedRole = {
            ...selectedRole,
            enabled_modes: restoredModes,
            default_mode: snapshot.defaultMode && restoredModes.includes(snapshot.defaultMode)
              ? snapshot.defaultMode
              : restoredModes.includes(selectedRole.default_mode) ? selectedRole.default_mode : preferredRoleMode(restoredModes),
          };
          if (addedAvatar || addedPersona || addedTool || addedKnowledge || addedAction || addedVariant || restoredPendingMode) setNotice("新建内容已选中，请保存角色配置");
          window.sessionStorage.removeItem(snapshotKey);
        }
      } catch { window.sessionStorage.removeItem(snapshotKey); }
      setRole(selectedRole);
      setActiveMode(selectedRole.default_mode);
      setSelectedRealtimeAvatarId(selectedRole.default_selections?.realtime?.avatar_id ?? null);
      setPersonas(loadedPersonas);
      setTools(loadedTools);
      setKnowledgeDocuments(loadedKnowledge);
      setKnowledgeIds(selectedKnowledgeIds);
      const nextAvatar = availableAvatars.find((item) => item.avatar_id === selectedRole.avatar_id) ?? null;
      const actionPreferences = readRoleActionPreferences(selectedRole.role_id, nextAvatar?.avatar_id ?? "");
      const nextActions = nextAvatar?.actions.filter((action) => !action.deleted_at && action.video_url) ?? [];
      const nextOfflineActions = nextActions.filter((action) => action.talking_variants?.some((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url));
      const requestedActionId = returnedActionId ?? actionPreferences.actionId ?? (
        selectedRole.default_mode === "offline"
          ? selectedRole.default_selections?.offline?.action_id
          : selectedRole.default_mode === "motion" || selectedRole.default_mode === "lip-sync"
            ? selectedRole.default_selections?.[selectedRole.default_mode]?.action_id
            : null
      ) ?? null;
      const previewActions = selectedRole.default_mode === "offline" ? nextOfflineActions : nextActions;
      const nextActionId = previewActions.some((action) => action.avatar_action_id === requestedActionId) ? requestedActionId : previewActions[0]?.avatar_action_id ?? null;
      const nextSelectedAction = nextActions.find((action) => action.avatar_action_id === nextActionId);
      const requestedVariantId = (nextActionId ? actionPreferences.variants[nextActionId] : undefined)
        ?? (selectedRole.default_selections?.offline?.action_id === nextActionId
          ? selectedRole.default_selections?.offline?.talking_variant_id ?? null : null);
      const nextTalkingVariants = nextSelectedAction?.talking_variants
        ?.filter((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url
          && variant.source_video_url === nextSelectedAction.video_url) ?? [];
      setAvatars(avatarRecords);
      setAvatar(nextAvatar);
      setActiveActionId(nextActionId);
      setActiveTalkingVariantId(nextTalkingVariants.some((variant) => variant.id === requestedVariantId) ? requestedVariantId : nextTalkingVariants[0]?.id ?? null);
      setLoading(false);
    }).catch((cause) => {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : "角色读取失败");
      setLoading(false);
    });
    return () => controller.abort();
  }, [resourceRevision, roleId]);

  const actions = useMemo(() => avatar?.actions.filter((action) => !action.deleted_at && action.video_url) ?? [], [avatar]);
  const offlineActions = actions.filter((action) => action.talking_variants?.some((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url));
  const hasTalkingMaterial = offlineActions.length > 0;
  const activeAction = actions.find((action) => action.avatar_action_id === activeActionId) ?? null;
  const activeTalkingVariants = activeAction?.talking_variants?.filter((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === activeAction.video_url) ?? [];
  const realtimeAvatars = [...personalRealtimeAvatars, ...officialRealtimeAvatars];
  const activeRealtimeAvatar = selectedRealtimeAvatarId
    ? realtimeAvatars.find((item) => item.id === selectedRealtimeAvatarId) ?? null
    : null;
  const realtimeReady = realtimeConfigured && Boolean(activeRealtimeAvatar);
  const lipSyncReady = personalLipsyncReady && capabilities?.localRenderer.state === "available";
  const displayMode = roleDetailDisplayMode(activeMode, lipSyncReady, Boolean(role?.enabled_modes.includes("offline") && activeTalkingVariants.length));
  const previewVideoUrl = displayMode === "offline"
    ? previewKind === "talking"
      ? activeTalkingVariants.find((variant) => variant.id === activeTalkingVariantId)?.video_url
      : activeAction?.video_url
    : displayMode === "lip-sync" || displayMode === "motion" ? activeAction?.video_url : undefined;
  const previewImageUrl = role?.avatar_image_url;
  const autoSaveReady = Boolean(role?.display_name.trim());
  const autoSaveFingerprint = role ? roleSaveFingerprint(role, knowledgeIds) : "";

  useEffect(() => {
    if (!role || !autoSaveReady || saving || autoSaveFingerprint === lastSavedFingerprintRef.current) return;
    if (autoSaveTimerRef.current !== null) window.clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = window.setTimeout(() => {
      autoSaveTimerRef.current = null;
      const draft = role;
      const draftKnowledgeIds = knowledgeIds;
      setSaving(true);
      setError("");
      void persistRoleDraft(draft, draftKnowledgeIds).then(({ updated, knowledgeIds: savedKnowledgeIds }) => {
        lastSavedFingerprintRef.current = roleSaveFingerprint(updated, savedKnowledgeIds);
        lastSavedAvatarIdRef.current = updated.avatar_id;
        setNotice("所有更改已自动保存");
      }).catch((cause) => {
        setError(cause instanceof Error ? cause.message : "角色保存失败");
      }).finally(() => setSaving(false));
    }, role.avatar_id !== lastSavedAvatarIdRef.current ? 0 : 700);
    return () => {
      if (autoSaveTimerRef.current !== null) window.clearTimeout(autoSaveTimerRef.current);
      autoSaveTimerRef.current = null;
    };
  }, [autoSaveFingerprint, autoSaveReady, knowledgeIds, role, saving]);

  function rememberResourceIds() {
    window.sessionStorage.setItem(`openrealtime-role-resource-return:${roleId}`, JSON.stringify({
      avatars: avatars.map((item) => item.avatar_id),
      personas: personas.map((item) => item.personaId),
      tools: tools.map((item) => item.tool_id),
      knowledge: knowledgeDocuments.map((item) => item.document_id),
      actions: avatars.flatMap((item) => item.actions.map((action) => action.avatar_action_id)),
      variants: avatars.flatMap((item) => item.actions.flatMap((action) => (action.talking_variants ?? []).map((variant) => variant.id))),
      enabledModes: role?.enabled_modes,
      defaultMode: role?.default_mode,
    }));
  }

  const assetManagement = useRoleAssetManagement(handleAssetChange);

  function handleAssetChange(change: AssetChange) {
    setAvatars(current => applyAssetChange(current, change));
    if (avatar?.avatar_id === change.avatarId && role) {
      const updated = applyAssetChange([avatar], change)[0];
      const available = updated.deleted_at ? null : updated;
      const valid = validRoleAssetSelection(available, activeActionId, activeTalkingVariantId);
      setAvatar(available);
      setActiveActionId(valid.actionId);
      setActiveTalkingVariantId(valid.variantId);
      setRole(current => current ? { ...current, avatar_id: available?.avatar_id ?? null,
        avatar_image_url: available?.source_image_url ?? null,
        default_selections: cleanRoleAssetDefaults(available, current.default_selections) } : current);
      if (activeActionId && !valid.actionId) setPreviewKind("motion");
    }
    setNotice("素材已更新");
  }

  function openProductionTask(task: AvatarWorkbenchTask) {
    if (task !== "avatar") rememberResourceIds();
    setProductionTask(task);
  }

  function closeProductionTask() {
    setProductionTask(null);
    setResourceRevision((revision) => revision + 1);
  }

  async function finishRealtimeCreation(hostedAvatar: AnamHostedAvatar) {
    if (!role) return;
    const updatedRole = { ...role, default_selections: { ...role.default_selections, realtime: { avatar_id: hostedAvatar.id } } };
    saveHostedAvatarProfile(hostedAvatar.id, {
      displayName: role.display_name,
      voiceProvider: role.voice_provider,
      voiceId: role.voice_id,
      voiceDialect: role.voice_dialect ?? "",
      personaId: role.persona_id,
      toolIds: role.tool_ids,
    });
    setSelectedRealtimeAvatarId(hostedAvatar.id);
    setRole(updatedRole);
    setCreatingRealtimeAvatar(false);
    setRealtimeCatalogRevision((revision) => revision + 1);
    setSaving(true);
    setError("");
    try {
      const { updated, knowledgeIds: savedKnowledgeIds } = await persistRoleDraft(updatedRole, knowledgeIds);
      lastSavedFingerprintRef.current = roleSaveFingerprint(updated, savedKnowledgeIds);
      const response = await fetch(`/api/hosted-avatar-settings/${encodeURIComponent(hostedAvatar.id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memoryEnabled: role.memory_enabled, documentIds: knowledgeIds, toolIds: role.tool_ids, sourceRoleId: role.role_id }),
      });
      if (!response.ok) throw new Error("实时数字人已创建并关联角色，但知识库或记忆同步失败，请在资源库检查配置");
      setNotice("实时数字人已创建，角色配置已同步");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "实时数字人已创建，但角色关联保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function submit({ automatic = false }: { automatic?: boolean } = {}): Promise<RoleRecord | null> {
    if (!role || saving || !configurationReady) return null;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const { updated, knowledgeIds: savedKnowledgeIds } = await persistRoleDraft(role, knowledgeIds);
      lastSavedFingerprintRef.current = roleSaveFingerprint(updated, savedKnowledgeIds);
      setRole(updated);
      setNotice(automatic ? "所有更改已自动保存" : "角色配置已保存");
      if (!automatic) router.refresh();
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "角色保存失败");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function startConversation() {
    if (displayMode === "lip-sync" && !lipSyncReady) {
      setError("离线加口型需要已就绪的个人口型服务和运行时；请在设置中检查连接");
      return;
    }
    const saved = await submit();
    if (!saved) return;
    announceNavigationStart();
    router.push(conversationHref(saved, displayMode, activeActionId, displayMode === "offline" ? activeTalkingVariantId : null));
  }

  async function setAsDefault() {
    if (!role || settingDefault) return;
    setSettingDefault(true);
    setDefaultError("");
    try {
      const response = await fetch("/api/user/default-role", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roleId: role.role_id }),
      });
      const data = await readJsonResponse<{ roleId?: string; error?: string }>(response, "默认角色设置失败");
      if (!response.ok || !data.roleId) throw new Error(data.error || "默认角色设置失败");
      setDefaultRoleId(data.roleId);
      setNotice("已设为新对话的默认角色");
    } catch (cause) { setDefaultError(cause instanceof Error ? cause.message : "默认角色设置失败"); }
    finally { setSettingDefault(false); }
  }

  function selectAvatar(avatarId: string, createdAvatar?: OwnedAvatarRecord) {
    if (!role) return;
    const nextAvatar = createdAvatar ?? avatars.find((item) => item.avatar_id === avatarId) ?? null;
    const identityChanged = role.avatar_id !== nextAvatar?.avatar_id;
    const requestedModes = identityChanged ? role.enabled_modes.filter((mode) => mode !== "realtime") : role.enabled_modes;
    const enabledModes: RolePresentationMode[] = requestedModes.length ? requestedModes : ["conversation"];
    const previewModes = enabledRoleModesForAvatar(requestedModes, nextAvatar);
    const previewMode = previewModes.includes(activeMode) ? activeMode : preferredRoleMode(previewModes);
    const nextActions = nextAvatar?.actions.filter((action) => !action.deleted_at && action.video_url) ?? [];
    const previewActions = previewMode === "offline" ? nextActions.filter((action) => action.talking_variants?.some((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url)) : nextActions;
    const nextAction = previewActions[0] ?? null;
    const nextVariant = nextAction?.talking_variants?.find((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === nextAction.video_url) ?? null;
    setAvatar(nextAvatar);
    setActiveActionId(nextAction?.avatar_action_id ?? null);
    setActiveTalkingVariantId(nextVariant?.id ?? null);
    setPreviewKind("motion");
    setActiveMode(previewMode);
    if (identityChanged) setSelectedRealtimeAvatarId(null);
    setRole({
      ...role,
      avatar_id: nextAvatar?.avatar_id ?? null,
      avatar_image_url: nextAvatar?.source_image_url ?? null,
      enabled_modes: enabledModes,
      default_mode: enabledModes.includes(role.default_mode) ? role.default_mode : preferredRoleMode(previewModes),
      default_selections: {
        ...(!identityChanged && role.default_selections?.realtime ? { realtime: role.default_selections.realtime } : {}),
        ...(nextAction ? {
          motion: { action_id: nextAction.avatar_action_id },
          "lip-sync": { action_id: nextAction.avatar_action_id },
          ...(nextVariant ? { offline: { action_id: nextAction.avatar_action_id, talking_variant_id: nextVariant.id } } : {}),
        } : {}),
      },
    });
  }

  async function selectPresentationPreview(mode: RolePresentationMode, actionId?: string, talkingVariantId?: string, nextPreviewKind?: "motion" | "talking") {
    setActiveMode(mode);
    if (nextPreviewKind) setPreviewKind(nextPreviewKind);
    if (mode === "conversation" || mode === "realtime") return;
    const nextActionId = actionId ?? (mode === "offline" ? offlineActions[0]?.avatar_action_id : actions[0]?.avatar_action_id) ?? null;
    setActiveActionId(nextActionId);
    if (mode !== "offline") {
      setActiveTalkingVariantId(null);
      return;
    }
    const nextSelectedAction = actions.find((action) => action.avatar_action_id === nextActionId);
    const nextVariants = nextSelectedAction?.talking_variants
      ?.filter((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url
        && variant.source_video_url === nextSelectedAction.video_url) ?? [];
    setActiveTalkingVariantId(talkingVariantId ?? nextVariants[0]?.id ?? null);
  }

  function startConfigDrag(event: ReactPointerEvent<HTMLElement>) {
    if (window.innerWidth <= 760 || !configPanelRef.current) return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select, label")) return;
    const rect = configPanelRef.current.getBoundingClientRect();
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: configPosition.x,
      originY: configPosition.y,
      minX: configPosition.x - rect.left + 12,
      maxX: configPosition.x + window.innerWidth - rect.right - 12,
      minY: configPosition.y - rect.top + 12,
      maxY: configPosition.y + window.innerHeight - rect.bottom - 12,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDraggingConfig(true);
  }

  function moveConfigPanel(event: ReactPointerEvent<HTMLElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setConfigPosition({
      x: Math.min(drag.maxX, Math.max(drag.minX, drag.originX + event.clientX - drag.startX)),
      y: Math.min(drag.maxY, Math.max(drag.minY, drag.originY + event.clientY - drag.startY)),
    });
  }

  function stopConfigDrag(event: ReactPointerEvent<HTMLElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDraggingConfig(false);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function startConfigResize(event: ReactPointerEvent<HTMLElement>) {
    if (window.innerWidth <= 760) return;
    event.stopPropagation();
    resizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      originWidth: configPanelRef.current?.getBoundingClientRect().width ?? configWidth,
      maxWidth: Math.min(720, window.innerWidth - 48),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizingConfig(true);
  }

  function resizeConfigPanel(event: ReactPointerEvent<HTMLElement>) {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    setConfigWidth(Math.min(resize.maxWidth, Math.max(400, resize.originWidth + resize.startX - event.clientX)));
  }

  function stopConfigResize(event: ReactPointerEvent<HTMLElement>) {
    if (resizeRef.current?.pointerId !== event.pointerId) return;
    resizeRef.current = null;
    setResizingConfig(false);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function resizeConfigWithKeyboard(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setConfigWidth((width) => Math.min(720, Math.max(400, width + (event.key === "ArrowLeft" ? 24 : -24))));
  }

  function toggleConfigModule(module: Exclude<ConfigModule, null>) {
    setOpenModule((current) => current === module ? null : module);
  }

  function toggleConfigSection(section: Exclude<ConfigSection, null>) {
    setOpenSection((current) => current === section ? null : section);
    setOpenModule(null);
  }

  function presentationModeAvailable(mode: RolePresentationMode) {
    if (mode === "motion") return false;
    return mode === "conversation"
      || (mode === "realtime" ? realtimeReady
        : mode === "offline" ? hasTalkingMaterial
          : Boolean(avatar && actions.length));
  }

  function togglePresentationMode(mode: RolePresentationMode) {
    if (!role || mode === "motion") return;
    if (mode === "realtime" && !realtimeConfigured) return;
    if (mode === "lip-sync" && (!personalLipsyncReady || capabilities?.localRenderer.state !== "available")) return;
    const checked = role.enabled_modes.includes(mode);
    if (checked && role.enabled_modes.length === 1) return;
    const enabledModes = checked
      ? role.enabled_modes.filter((item) => item !== mode)
      : ROLE_PRESENTATION_MODES.filter((item) => item === mode || role.enabled_modes.includes(item));
    const defaultMode = !checked && mode === "offline" && role.default_mode === "conversation"
      ? "offline"
      : enabledModes.includes(role.default_mode) ? role.default_mode : preferredRoleMode(enabledModes);
    setRole({ ...role, enabled_modes: enabledModes, default_mode: defaultMode,
      default_selections: !checked && mode === "realtime" && activeRealtimeAvatar
        ? { ...role.default_selections, realtime: { avatar_id: activeRealtimeAvatar.id } } : role.default_selections });
    if (!enabledModes.includes(activeMode)) setActiveMode(defaultMode);
    if (!checked) {
      const nextSection = !avatar && mode !== "conversation" ? "avatar"
        : mode === "realtime" && !realtimeReady ? "realtime"
          : (mode === "offline" || mode === "lip-sync") && !actions.length ? "action"
            : mode === "offline" && !selectedTalkingVariant ? "talking"
              : "presentation";
      setOpenSection(nextSection);
      setOpenModule(null);
    }
  }

  if (loading) return <div className={styles.loading}><LoaderCircle /><span>{t("正在读取角色")}</span></div>;
  if (!role) return <div className={styles.missing}><h1>{t("找不到这个角色")}</h1><p>{t(error)}</p><BackLink href="/roles" label={t("返回角色列表")} /></div>;

  const selectedVoiceName = describeVoiceSelection({ provider: role.voice_provider, voice: role.voice_id, dialect: role.voice_dialect ?? "" });
  const needsAvatar = role.enabled_modes.some((mode) => mode !== "conversation" && mode !== "realtime")
    || (role.enabled_modes.includes("realtime") && !avatar);
  const needsRealtime = role.enabled_modes.includes("realtime");
  const needsAction = role.enabled_modes.includes("offline") || role.enabled_modes.includes("lip-sync");
  const needsTalking = role.enabled_modes.includes("offline");
  const configuredPresentationModes = role.enabled_modes.filter((mode) => mode !== "lip-sync" || lipSyncReady);
  const selectablePresentationModes: RolePresentationMode[] = configuredPresentationModes.length ? configuredPresentationModes : ["conversation"];
  const defaultPresentationMode = selectablePresentationModes.includes(role.default_mode) ? role.default_mode : preferredRoleMode(selectablePresentationModes);
  const selectedTalkingVariant = activeTalkingVariants.find((variant) => variant.id === activeTalkingVariantId) ?? null;
  const configurationIssues = [
    ...(!role.display_name.trim() ? ["角色名称"] : []),
    ...(needsAvatar && !avatar ? ["数字人形象"] : []),
    ...(needsRealtime && !realtimeReady ? ["实时驱动"] : []),
    ...(needsAction && !activeAction ? ["动作底片"] : []),
    ...(needsTalking && !selectedTalkingVariant ? ["口型对齐"] : []),
  ];
  const configurationReady = configurationIssues.length === 0;
  const previewConfig = {
    ...DEFAULT_AVATAR_DISPLAY_CONFIG,
    renderPath: displayMode === "offline" ? "orchestrated" as const : "segmented" as const,
    segmentedPresetId: "custom-upload",
    segmentedAvatarId: role.avatar_id ?? "",
    segmentedDisplayName: avatar?.display_name ?? role.display_name,
    segmentedAvatarActionId: activeActionId ?? "",
    motionTalkingVariantId: displayMode === "offline" ? activeTalkingVariantId ?? undefined : undefined,
  };

  return <div className={`${homePreviewStyles.workspace} ${styles.page}`} data-mode="avatar" data-panel-open={openPanel ?? "none"}>
    <div className={homePreviewStyles.preview} aria-live="polite">
      <div className={homePreviewStyles.atmosphere} aria-hidden="true"><i /><i /><i /></div>
      <div className={homePreviewStyles.avatarPreview} data-visible="true">
        {previewVideoUrl && displayMode !== "conversation" ? <>
          <video className={homePreviewStyles.avatarPreviewMotionBackdrop} key={`backdrop:${displayMode}:${activeActionId}`} src={previewVideoUrl} autoPlay muted loop playsInline aria-hidden="true" />
          <video className={homePreviewStyles.avatarPreviewForeground} data-fit="contain" key={`${displayMode}:${activeActionId}`} src={previewVideoUrl} autoPlay muted loop playsInline aria-label={"" + (role.display_name) + t(" 动作预览")} />
        </> : previewImageUrl ? <>
          <Image className={homePreviewStyles.avatarPreviewMotionBackdrop} src={previewImageUrl} alt="" aria-hidden="true" fill priority sizes="100vw" unoptimized />
          <Image className={homePreviewStyles.avatarPreviewForeground} src={previewImageUrl} alt={"" + (role.display_name) + t(" 数字人预览")} fill priority sizes="100vw" unoptimized />
        </> : <div className={homePreviewStyles.avatarPreviewPlaceholder}><UserRound aria-hidden="true" /></div>}
        <div className={homePreviewStyles.avatarWash} aria-hidden="true" />
      </div>
      <div className={homePreviewStyles.previewCopy}>
        <span><i />{ROLE_MODE_LABELS[displayMode]}</span>
        <h1>{role.display_name}</h1>
        <p className={styles.personaName}>{role.persona_name ?? t("通用助手")}</p>
      </div>
    </div>

    <header className={styles.topbar}>
      <Link href="/roles" aria-label={t("返回角色列表")}><ArrowLeft /></Link>
      <div className={styles.topbarTitle}><strong>{role.display_name}</strong></div>
      <div className={styles.topbarActions}>
        <button className={styles.defaultAction} type="button" disabled={settingDefault || defaultRoleId === role.role_id} onClick={() => void setAsDefault()}><Star fill={defaultRoleId === role.role_id ? "currentColor" : "none"} />{defaultRoleId === role.role_id ? t("默认角色") : t("设为默认")}</button>
        <button className={styles.settingsAction} type="button" aria-label={t("打开角色配置")} aria-expanded={openPanel === "config"} onClick={() => setOpenPanel(openPanel === "config" ? null : "config")}><Settings2 />{t("角色设置")}</button>
      </div>
    </header>

    <aside
      ref={configPanelRef}
      className={styles.configPanel}
      data-open={openPanel === "config"}
      data-dragging={draggingConfig}
      data-resizing={resizingConfig}
      aria-label={t("角色配置")}
      aria-hidden={openPanel !== "config"}
      inert={openPanel !== "config"}
      style={{ "--config-x": `${configPosition.x}px`, "--config-y": `${configPosition.y}px`, "--config-width": `${configWidth}px` } as CSSProperties}
    >
      <div className={styles.configResizeHandle} role="separator" aria-label={t("调整配置窗口宽度")} aria-orientation="vertical" tabIndex={0} onPointerDown={startConfigResize} onPointerMove={resizeConfigPanel} onPointerUp={stopConfigResize} onPointerCancel={stopConfigResize} onKeyDown={resizeConfigWithKeyboard}><span /></div>
      <section className={styles.configContent} aria-live="polite">
        <header className={styles.configHeader} onPointerDown={startConfigDrag} onPointerMove={moveConfigPanel} onPointerUp={stopConfigDrag} onPointerCancel={stopConfigDrag}>
          <GripHorizontal className={styles.dragHandle} aria-hidden="true" />
          <div className={styles.configTitle}>
            <small>{t("角色设置")}</small>
            <strong>{role.display_name}</strong>
          </div>
          <div className={styles.configHeaderActions}>
            <button type="button" aria-label={t("关闭角色配置")} onPointerDown={(event) => event.stopPropagation()} onClick={() => setOpenPanel(null)}><X /></button>
          </div>
        </header>
        <div className={styles.configBody}>
          <div className={styles.configView}>
            <ConfigTaskModule id="foundation" icon={<Sparkles />} title={t("角色基础")} detail={role.display_name} status="已配置" done openSection={openSection} onOpen={toggleConfigSection}>
              <div className={styles.foundationGrid}>
                <label className={styles.field}><span>{t("角色名称")}</span><div className={styles.roleNameRow}><input value={role.display_name} readOnly={!editingRoleName} maxLength={80} onChange={(event) => setRole({ ...role, display_name: event.target.value })} /><button type="button" onClick={() => setEditingRoleName((editing) => !editing)}>{editingRoleName ? <Check /> : <Pencil />}{editingRoleName ? t("完成") : t("编辑")}</button></div></label>
            <section className={styles.settingModule} data-open={openModule === "voice"}>
              <button className={styles.settingSummary} type="button" aria-label={t("声音设置")} aria-expanded={openModule === "voice"} onClick={() => toggleConfigModule("voice")}><Volume2 /><span><small>{t("声音")}</small><strong>{selectedVoiceName}</strong><em>{TTS_PROVIDER_OPTIONS.find((item) => item.value === role.voice_provider)?.label}</em></span><ChevronDown /></button>
              {openModule === "voice" ? <div className={styles.settingDetails}>
                <VoiceSelector showCurrent={false} roleId={role.role_id} value={{ provider: role.voice_provider, voice: role.voice_id, dialect: role.voice_dialect ?? "" }} onChange={(voice) => setRole({ ...role, voice_provider: voice.provider, voice_id: voice.voice, voice_dialect: voice.dialect })} onSelectionCommit={() => setOpenModule(null)} allowClone allowManagement={false} />
              </div> : null}
            </section>

            <section className={styles.settingModule} data-open={openModule === "persona"}>
              <button className={styles.settingSummary} type="button" aria-label={t("人设设置")} aria-expanded={openModule === "persona"} onClick={() => toggleConfigModule("persona")}><Sparkles /><span><small>{t("人设")}</small><strong>{role.persona_name ?? t("默认助手")}</strong><em>{personas.find((item) => item.personaId === role.persona_id)?.intro || t("使用角色默认的对话风格")}</em></span><ChevronDown /></button>
              {openModule === "persona" ? <div className={styles.settingDetails}>
                <PersonaChoiceGrid personas={personas} value={role.persona_id} onChange={(personaId) => setRole({ ...role, persona_id: personaId, persona_name: personas.find((item) => item.personaId === personaId)?.personaName ?? null })} />
                <div className={styles.resourceRows}><Link href={`/resources?tab=personas&return_to=${encodeURIComponent(role.role_id)}`} onClick={rememberResourceIds}><Plus /><span><strong>{t("新建人设")}</strong><small>{t("创建后自动回到当前角色")}</small></span><ChevronRight /></Link></div>
              </div> : null}
            </section>

            <section className={styles.settingModule} data-open={openModule === "tools"}>
              <button className={styles.settingSummary} type="button" aria-label={t("工具使用设置")} aria-expanded={openModule === "tools"} onClick={() => toggleConfigModule("tools")}><Wrench /><span><small>{t("工具使用")}</small><strong>{role.tool_ids.length ? t("已选择 ") + (role.tool_ids.length) + t(" 个") : t("暂未选择")}</strong><em>{t("内置、个人与共享工具")}</em></span><ChevronDown /></button>
              {openModule === "tools" ? <div className={styles.settingDetails}>
                <div className={styles.moduleToolbar}><span>{t("选择角色可调用的工具")}</span><div className={styles.moduleToolbarActions}><Link href={`/settings/permissions?roleId=${encodeURIComponent(role.role_id)}`} aria-label={t("设置当前角色的工具权限")}><Settings2 />{t("工具权限")}</Link><Link href={`/resources?tab=tools&return_to=${encodeURIComponent(role.role_id)}`} onClick={rememberResourceIds}><Plus />{t("新建")}</Link></div></div>
                <div className={styles.capabilityList} aria-label={t("角色工具")}>{tools.map((tool) => {
                const disabled = !tool.enabled || (!tool.builtin && !tool.endpoint && !tool.public_enabled);
                const scope = tool.builtin ? "内置" : tool.public_enabled ? "共享" : "个人";
                return <label key={tool.tool_id} data-disabled={disabled}><input type="checkbox" disabled={disabled} checked={role.tool_ids.includes(tool.tool_id)} onChange={(event) => setRole({ ...role, tool_ids: event.target.checked ? [...role.tool_ids, tool.tool_id] : role.tool_ids.filter((item) => item !== tool.tool_id) })} /><span><strong>{tool.display_name}</strong><small>{disabled ? t("需要补充服务地址后才能执行") : tool.description}</small></span><em data-scope={scope}>{tool.builtin ? t("内置") : tool.public_enabled ? t("共享") : t("个人")}</em></label>;
                })}</div>
              </div> : null}
            </section>

            <section className={styles.settingModule} data-open={openModule === "knowledge"}>
              <button className={styles.settingSummary} type="button" aria-label={t("知识库设置")} aria-expanded={openModule === "knowledge"} onClick={() => toggleConfigModule("knowledge")}><BookOpen /><span><small>{t("知识库")}</small><strong>{knowledgeIds.length ? t("已选择 ") + (knowledgeIds.length) + t(" 份") : t("暂未选择")}</strong><em>{t("关联资源库中的资料")}</em></span><ChevronDown /></button>
              {openModule === "knowledge" ? <div className={styles.settingDetails}>
                <div className={styles.moduleToolbar}><span>{t("选择对话时可检索的资料，可与其他角色共用")}</span><Link href={`/resources?tab=knowledge&return_to=${encodeURIComponent(role.role_id)}`} onClick={rememberResourceIds}><Plus />{t("新建")}</Link></div>
                <div className={styles.capabilityList} aria-label={t("角色知识库资料")}>{knowledgeDocuments.map((doc) => <label key={doc.document_id}><input type="checkbox" checked={knowledgeIds.includes(doc.document_id)} onChange={(event) => setKnowledgeIds((old) => event.target.checked ? [...old, doc.document_id] : old.filter((id) => id !== doc.document_id))} /><span><strong>{doc.title}</strong><small>{doc.source_url ? t("包含外部来源") : t("本地资料")}</small></span><em>{doc.owner_id === null ? t("共享") : t("个人")}</em></label>)}</div>
              </div> : null}
            </section>

            <button className={styles.memoryButton} type="button" aria-pressed={role.memory_enabled} data-selected={role.memory_enabled} onClick={() => setRole({ ...role, memory_enabled: !role.memory_enabled })}><span className={styles.memoryCheck}>{role.memory_enabled ? <Check /> : null}</span><span><strong>{t("长期记忆")}</strong><small>{t("按当前用户与角色隔离保存，随时可以关闭")}</small></span><em>{role.memory_enabled ? t("已启用") : t("未启用")}</em></button>
            <details className={styles.advancedProviders}>
              <summary>{t("高级配置")}</summary>
              <p>{t("留空时使用“供应商”中的默认配置。")}</p>
              <label className={styles.field}><span>{t("ASR 供应商")}</span><SelectMenu fullWidth value={String(role.asr_provider ?? "")} ariaLabel={t("角色 ASR 供应商")} options={[{ value: "", label: t("使用供应商默认配置") }, ...(PROVIDER_CATALOG.asr.map((provider) => ({ value: String(provider.id), label: String(provider.name) })))]} onChange={value => setRole({ ...role, asr_provider: value as RoleRecord["asr_provider"] || null })} /></label>
              <label className={styles.field}><span>{t("LLM 供应商")}</span><SelectMenu fullWidth value={String(role.llm_provider ?? "")} ariaLabel={t("角色 LLM 供应商")} options={[{ value: "", label: t("使用供应商默认配置") }, ...(PROVIDER_CATALOG.llm.map((provider) => ({ value: String(provider.id), label: String(provider.name) })))]} onChange={value => setRole({ ...role, llm_provider: value as RoleRecord["llm_provider"] || null })} /></label>
            </details>
              </div>
            </ConfigTaskModule>

            <ConfigTaskModule id="presentation" icon={<MessageCircle />} title={t("呈现模式")} detail={configuredPresentationModes.map((mode) => ROLE_MODE_LABELS[mode]).join("、")} status={`当前可用 ${configuredPresentationModes.length} 项`} done={configuredPresentationModes.length > 0} openSection={openSection} onOpen={toggleConfigSection}>
              <div className={styles.taskInner}>
                <div className={styles.modeOptions} aria-label={t("选择可用呈现方式")}>{ROLE_PRESENTATION_MODES.filter((mode) => mode !== "motion" && (mode !== "realtime" || realtimeConfigured) && (mode !== "lip-sync" || (personalLipsyncReady && capabilities?.localRenderer.state === "available"))).map((mode) => {
                  const available = presentationModeAvailable(mode);
                  const checked = role.enabled_modes.includes(mode);
                  return <button key={mode} type="button" disabled={checked && role.enabled_modes.length === 1} aria-pressed={checked} data-selected={checked} data-ready={available} onClick={() => togglePresentationMode(mode)}><span className={styles.modeState}>{checked ? <Check /> : null}</span><span><strong>{ROLE_MODE_LABELS[mode]}</strong><small>{mode === "conversation" ? t("文字与语音对话") : available ? t("当前形象素材可用") : t("选择后继续完成所需配置")}</small></span></button>;
                })}</div>
                <label className={styles.field}><span>{t("默认呈现方式")}</span><SelectMenu fullWidth value={String(defaultPresentationMode)} ariaLabel={t("默认呈现方式")} options={[...(selectablePresentationModes.map((mode) => ({ value: String(mode), label: t(String(ROLE_MODE_LABELS[mode])) })))]} onChange={value => setRole({ ...role, default_mode: value as RolePresentationMode })} /></label>
              </div>
            </ConfigTaskModule>

            {needsAvatar ? <ConfigTaskModule id="avatar" icon={<UserRound />} title={t("数字人形象")} detail={avatar?.display_name ?? "未选择形象"} status={avatar ? "已选择" : "待配置"} done={Boolean(avatar)} openSection={openSection} onOpen={toggleConfigSection}>
              <div className={styles.taskInner}>
                <AvatarChoiceGrid avatars={avatars} value={role.avatar_id} onChange={selectAvatar} onManage={assetManagement.manage} busy={assetManagement.busy} />
                <DeletedAssets avatars={avatars} onManage={assetManagement.manage} busy={assetManagement.busy} />
                <div className={styles.resourceRows}>
                  <button type="button" onClick={() => openProductionTask("avatar")}><Plus /><span><strong>{t("新建形象")}</strong><small>{t("在当前页面完成并自动带回")}</small></span><ChevronRight /></button>
                </div>
              </div>
            </ConfigTaskModule> : null}

            {needsRealtime ? <ConfigTaskModule id="realtime" icon={<Radio />} title={t("实时数字人")} detail={activeRealtimeAvatar?.displayName ?? "需要完成实时数字人配置"} status={realtimeReady ? "已就绪" : "待配置"} done={realtimeReady} openSection={openSection} onOpen={toggleConfigSection}>
              <div className={styles.taskInner}>
                <div className={styles.requirementState} data-ready={realtimeReady}><span>{realtimeReady ? <Check /> : <Radio />}</span><div><strong>{realtimeReady ? t("实时数字人已可用") : t("尚未创建实时数字人")}</strong><small>{t("使用当前角色形象创建；声音与人设在资源库设置")}</small></div></div>
                <div className={styles.resourceRows}><button type="button" disabled={!avatar} onClick={() => setCreatingRealtimeAvatar(true)}><Plus /><span><strong>{t("创建数字人形象")}</strong><small>{avatar ? t("使用当前角色的「") + (avatar.display_name) + t("」形象创建") : t("请先为当前角色选择数字人形象")}</small></span><ChevronRight /></button></div>
              </div>
            </ConfigTaskModule> : null}

            {needsAction ? <ConfigTaskModule id="action" icon={<Film />} title={t("动作底片")} detail={activeAction?.display_name ?? (lipSyncReady ? "离线与离线加口型共用" : "离线数字人动作")} status={activeAction ? "已选择" : "待配置"} done={Boolean(activeAction)} openSection={openSection} onOpen={toggleConfigSection}>
              {avatar ? <><div className={styles.actionCardGrid}>{actions.map((action) => {
                const selected = activeActionId === action.avatar_action_id;
                const talkingCount = action.talking_variants?.filter((item) => !item.deleted_at && item.video_url).length ?? 0;
                return <AssetCard key={action.avatar_action_id} target={{ avatar, action }} onManage={assetManagement.manage} busy={assetManagement.busy}><button className={styles.actionCard} type="button" aria-label={t("选择动作 ") + (action.display_name) + ""} aria-pressed={selected} data-selected={selected} onClick={() => { const variants = action.talking_variants?.filter((item) => item.method === "lipforcing" && !item.deleted_at && item.video_url && item.source_video_url === action.video_url) ?? []; const rememberedId = readRoleActionPreferences(role.role_id, avatar.avatar_id).variants[action.avatar_action_id]; const variantId = variants.find((item) => item.id === rememberedId)?.id ?? variants[0]?.id; setActiveActionId(action.avatar_action_id); if (variants.length === 1 && role.enabled_modes.includes("offline")) setActiveMode("offline"); setPreviewKind("motion"); setActiveTalkingVariantId(variantId ?? null); rememberRoleActionSelection(role.role_id, avatar.avatar_id, action.avatar_action_id, variantId); setRole((current) => current ? { ...current, default_selections: { ...current.default_selections, motion: { action_id: action.avatar_action_id }, "lip-sync": { action_id: action.avatar_action_id } } } : current); }}><span className={styles.actionCardMedia}><PreviewVideo src={action.video_url ?? ""} poster={avatar.source_image_url} label={"" + (action.display_name) + t(" 动作预览")} />{selected ? <i><Check /></i> : null}</span><span className={styles.actionCardCopy}><strong>{action.display_name}</strong><small>{talkingCount ? "" + (talkingCount) + t(" 个口型对齐") : t("动作底片")}</small></span></button></AssetCard>;
              })}<button className={styles.newActionCard} type="button" aria-label={t("新建动作")} onClick={() => openProductionTask("motion")}><span><Plus /></span><strong>{t("新建动作")}</strong><small>{t("上传或生成新的动作底片")}</small></button></div>{actions.length ? null : <p className={styles.actionEmptyHint}>{t("当前形象还没有动作底片，从这里创建第一个动作。")}</p>}<DeletedAssets actionAvatar={avatar} onManage={assetManagement.manage} busy={assetManagement.busy} /></> : <p className={styles.emptyHint}>{t("请先选择数字人形象。")}</p>}
            </ConfigTaskModule> : null}

            {needsTalking ? <ConfigTaskModule id="talking" icon={<Volume2 />} title={t("口型对齐")} detail={selectedTalkingVariant?.display_name ?? "离线模式需要与动作配对"} status={selectedTalkingVariant ? "已选择" : "待配置"} done={Boolean(selectedTalkingVariant)} openSection={openSection} onOpen={toggleConfigSection}>
              {avatar && activeAction ? <><div className={styles.actionCardGrid}>{activeTalkingVariants.map((variant) => {
                const selected = selectedTalkingVariant?.id === variant.id;
                return <AssetCard key={variant.id} target={{ avatar, action: activeAction, variant }} onManage={assetManagement.manage} busy={assetManagement.busy}><button className={styles.actionCard} type="button" aria-label={t("选择口型对齐 ") + (variant.display_name) + ""} aria-pressed={selected} data-selected={selected} onClick={() => { setActiveTalkingVariantId(variant.id); setPreviewKind("talking"); rememberRoleActionSelection(role.role_id, avatar.avatar_id, activeAction.avatar_action_id, variant.id); setRole((current) => current ? { ...current, default_selections: { ...current.default_selections, offline: { action_id: activeAction.avatar_action_id, talking_variant_id: variant.id } } } : current); }}><span className={styles.actionCardMedia}><PreviewVideo src={variant.video_url} poster={avatar.source_image_url} label={"" + (variant.display_name) + t(" 口型预览")} />{selected ? <i><Check /></i> : null}</span><span className={styles.actionCardCopy}><strong>{variant.display_name}</strong><small>{t("配对动作 · ")}{activeAction.display_name}</small></span></button></AssetCard>;
              })}<button className={styles.newActionCard} type="button" aria-label={t("新建口型对齐")} onClick={() => openProductionTask("talking")}><span><Plus /></span><strong>{t("新建口型对齐")}</strong><small>{t("为当前动作生成配对讲话视频")}</small></button></div>{activeTalkingVariants.length ? null : <p className={styles.actionEmptyHint}>{t("当前动作还没有口型对齐，从这里创建第一个素材。")}</p>}<DeletedAssets talkingAction={{ avatar, action: activeAction }} onManage={assetManagement.manage} busy={assetManagement.busy} /></> : <p className={styles.emptyHint}>{t("请先选择动作底片。")}</p>}
            </ConfigTaskModule> : null}
            {defaultError ? <p className={styles.error} role="alert">{defaultError}</p> : null}
          </div>
        </div>
        <footer className={styles.configFooter}><span><small>{configurationReady ? t("自动保存") : t("还需完成")}</small><strong>{saving ? t("正在保存更改…") : configurationReady ? t("所有更改自动保存") : configurationIssues.join("、")}</strong></span>{saving ? <LoaderCircle className={styles.spin} aria-hidden="true" /> : <Check aria-hidden="true" />}</footer>
      </section>
    </aside>

    <div className={`${homePreviewStyles.homeStartAction} ${styles.startAction}`}>
      <VoiceStartButton effect="magic-rings" connected disabled={saving || !configurationReady} ariaLabel={t("开始角色对话")} label={t("与 ") + (role.display_name) + t(" 对话")} hint={`${ROLE_MODE_LABELS[displayMode]} · ${displayMode === "conversation" ? "语音对话" : activeAction?.display_name ?? "角色形象"}`} onPress={() => void startConversation()} />
    </div>

    <HomeRoleModeControls
      role={role}
      mode={displayMode}
      avatar={avatar}
      config={previewConfig}
      canStart={!saving && configurationReady}
      visualTheme={visualTheme}
      themes={VOICE_VISUAL_THEME_OPTIONS}
      showRoleSelector={false}
      showRealtimeOption={false}
      lipSyncReady={lipSyncReady}
      runtimeLipSyncAvailable={capabilities?.localRenderer.state === "available"}
      onVisualThemeChange={setVisualTheme}
      onModeSelect={selectPresentationPreview}
      onStart={() => void startConversation()}
    />

    {assetManagement.dialog}
    {productionTask === "avatar" ? <AvatarUploadDialog
      onClose={() => setProductionTask(null)}
      onCreated={(createdAvatar) => {
        setAvatars((current) => [...current.filter((item) => item.avatar_id !== createdAvatar.avatar_id), createdAvatar]);
        selectAvatar(createdAvatar.avatar_id, createdAvatar);
        setProductionTask(null);
        setNotice("形象已创建并选中");
      }}
    /> : productionTask ? <AvatarProductionOverlay
      task={productionTask}
      avatarId={avatar?.avatar_id}
      actionId={activeActionId ?? undefined}
      method={productionTask === "talking" ? "lipforcing" : undefined}
      onClose={closeProductionTask}
      onComplete={closeProductionTask}
    /> : null}

    {creatingRealtimeAvatar && avatar ? <AvatarUploadDialog
      mode="realtime"
      sourceAvatar={avatar}
      sourceName={role.display_name}
      onClose={() => setCreatingRealtimeAvatar(false)}
      onRealtimeCreated={(_, hostedAvatar) => void finishRealtimeCreation(hostedAvatar)}
    /> : null}

    {error ? <p className={styles.floatingError} role="alert">{t(error)}</p> : null}
    {notice ? <p className={styles.floatingNotice} role="status"><Check />{t(notice)}</p> : null}
  </div>;
}

function ConfigTaskModule({ id, icon, title, detail, status, done, openSection, onOpen, children }: { id: Exclude<ConfigSection, null>; icon: ReactNode; title: string; detail: string; status: string; done: boolean; openSection: ConfigSection; onOpen: (id: Exclude<ConfigSection, null>) => void; children: ReactNode }) {
  const open = openSection === id;
  return <section className={styles.configTaskModule} data-open={open} data-done={done}><button className={styles.configTaskSummary} type="button" aria-expanded={open} onClick={() => onOpen(id)}><span className={styles.configTaskIcon}>{done ? <Check /> : icon}</span><span><strong>{title}</strong><small>{detail}</small></span><em>{status}</em><ChevronDown /></button>{open ? <div className={styles.configTaskContent}>{children}</div> : null}</section>;
}
