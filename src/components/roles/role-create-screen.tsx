"use client";
import { SelectMenu } from "@/components/ui/select-menu";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, Check, ChevronDown, ChevronRight, Film, LoaderCircle, MemoryStick, MessageCircle, Plus, Radio, Save, Sparkles, Upload, UserRound, Volume2, Wrench } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { BAILIAN_TTS_VOICE_OPTIONS, DEFAULT_TTS_VOICE, TTS_PROVIDER_OPTIONS, type TtsDialect, type TtsProvider } from "@/components/drawer/voice-options";
import { describeVoiceSelection, VoiceSelector } from "@/components/voice/voice-selector";
import type { PersonaSummary } from "@/lib/avatar-persona";
import { avatarActionPreviewSources } from "@/lib/avatar-action-preview";
import { fetchOwnedAvatars, fetchPersonalAvatars } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import type { KnowledgeDocument } from "@/lib/knowledge-catalog-repository";
import { readJsonResponse } from "@/lib/http-json-response";
import { selectedDefaultTtsProvider, type ProviderVoiceCatalog } from "@/lib/default-role-voice";
import { createRole } from "@/lib/role-catalog-client";
import { PROVIDER_CATALOG } from "@/lib/provider-catalog";
import { preferredRoleMode, ROLE_MODE_LABELS, type RolePresentationMode } from "@/lib/role-records";
import { fetchTools } from "@/lib/tool-catalog-client";
import type { ToolRecord } from "@/lib/tool-records";
import { AvatarChoiceGrid } from "./avatar-choice-grid";
import { usePersonalLipsyncReady } from "@/hooks/use-personal-lipsync-ready";
import { useAvatarCapabilities } from "@/hooks/use-avatar-capabilities";
import { ROLE_CREATE_DRAFT_KEY, useRoleCreationWorkbench } from "./role-creation-workbench-context";
import styles from "./role-create-screen.module.css";

type CreateMode = Exclude<RolePresentationMode, "motion">;
type ModuleId = "foundation" | "modes" | "avatar" | "realtime" | "action" | "talking";
type BaseSettingId = "voice" | "persona" | "tools" | "knowledge";
const CREATE_MODES: CreateMode[] = ["conversation", "realtime", "offline", "lip-sync"];
const RESOURCE_RETURN_KEY = "openrealtime:role-create-resource-return:v2";
const MODE_COPY: Record<CreateMode, { title: string; description: string }> = {
  conversation: { title: "对话", description: "文字与语音，不需要数字人素材" },
  realtime: { title: "实时", description: "需要形象和已确认的实时驱动" },
  offline: { title: "离线", description: "需要形象、动作和配对口型对齐" },
  "lip-sync": { title: "离线加口型", description: "需要形象和动作，口型运行时生成" },
};

interface DraftState {
  name: string; voiceProvider: TtsProvider; voiceId: string; voiceDialect: TtsDialect;
  voiceConfigurationTarget: string | null; voiceCustomized: boolean; personaId: string | null;
  asrProvider: "doubao" | "dashscope" | null; llmProvider: "deepseek" | "openai" | null;
  memoryEnabled: boolean; toolIds: string[]; knowledgeIds: string[]; modes: CreateMode[];
  defaultMode: CreateMode; avatarId: string | null; actionId: string | null; talkingVariantId: string | null;
}
const DEFAULT_DRAFT: DraftState = {
  name: "", voiceProvider: "doubao", voiceId: DEFAULT_TTS_VOICE, voiceDialect: "", voiceConfigurationTarget: null, voiceCustomized: false, personaId: null,
  asrProvider: null, llmProvider: null,
  memoryEnabled: true, toolIds: [], knowledgeIds: [], modes: ["offline"], defaultMode: "offline",
  avatarId: null, actionId: null, talkingVariantId: null,
};

export function RoleCreateScreen() {
  const personalLipsyncReady = usePersonalLipsyncReady();
  const { capabilities } = useAvatarCapabilities();
  const advancedModeReady = personalLipsyncReady && capabilities?.localRenderer.state === "available";
  const router = useRouter();
  const { latestResource, resourceRevision } = useRoleCreationWorkbench();
  const [draft, setDraft] = useState<DraftState>(DEFAULT_DRAFT);
  const [draftReady, setDraftReady] = useState(false);
  const [avatars, setAvatars] = useState<OwnedAvatarRecord[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [tools, setTools] = useState<ToolRecord[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeDocument[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(true);
  const [openModule, setOpenModule] = useState<ModuleId | null>("foundation");
  const [openBaseSetting, setOpenBaseSetting] = useState<BaseSettingId | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [panelWidth, setPanelWidth] = useState(500);
  const resizeRef = useRef<{ pointerId: number; startX: number; width: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(ROLE_CREATE_DRAFT_KEY) ?? "null") as Partial<DraftState> | null;
      if (stored) {
        const modes = Array.isArray(stored.modes) ? CREATE_MODES.filter((mode) => stored.modes?.includes(mode)) : DEFAULT_DRAFT.modes;
        const enabledModes = modes.length ? modes : DEFAULT_DRAFT.modes;
        setDraft({ ...DEFAULT_DRAFT, ...stored, modes: enabledModes,
          voiceCustomized: stored.voiceCustomized ?? Boolean(stored.voiceConfigurationTarget || stored.voiceDialect
            || (stored.voiceId && stored.voiceId !== DEFAULT_TTS_VOICE && stored.voiceId !== BAILIAN_TTS_VOICE_OPTIONS[0].value)),
          defaultMode: enabledModes.includes(stored.defaultMode as CreateMode) ? stored.defaultMode as CreateMode : preferredRoleMode(enabledModes) as CreateMode });
      }
      void fetch("/api/provider-instances", { cache: "no-store", signal: controller.signal })
          .then(async (response) => response.ok ? await response.json() as ProviderVoiceCatalog : null)
          .then((result) => {
            if (!result || controller.signal.aborted) return;
            const provider = selectedDefaultTtsProvider(result);
            if (!provider) return;
            const voiceProvider = provider === "dashscope" ? "bailian" : "doubao";
            setDraft((current) => !current.voiceCustomized && !current.voiceConfigurationTarget
              ? { ...current, voiceProvider, voiceId: voiceProvider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS[0].value : DEFAULT_TTS_VOICE }
              : current);
          }).catch(() => undefined).finally(() => { if (!controller.signal.aborted) setDraftReady(true); });
    } catch { window.sessionStorage.removeItem(ROLE_CREATE_DRAFT_KEY); setDraftReady(true); }
    return () => controller.abort();
  }, []);
  useEffect(() => { if (draftReady) window.sessionStorage.setItem(ROLE_CREATE_DRAFT_KEY, JSON.stringify(draft)); }, [draft, draftReady]);

  useEffect(() => {
    const controller = new AbortController();
    setResourcesLoading(true);
    void Promise.all([
      Promise.all([fetchPersonalAvatars(controller.signal), fetchOwnedAvatars(controller.signal).catch(() => [])])
        .then(([personal, shared]) => [...personal, ...shared].filter((item) => !item.deleted_at)),
      fetch("/api/personas", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? readJsonResponse<{ personas?: PersonaSummary[] }>(response, "Persona 列表读取失败") : { personas: [] }),
      fetchTools(controller.signal).catch(() => []),
      fetch("/api/knowledge", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? readJsonResponse<{ documents?: KnowledgeDocument[] }>(response, "知识库读取失败") : { documents: [] }),
    ]).then(([avatarRecords, personaPayload, toolRecords, knowledgePayload]) => {
      if (controller.signal.aborted) return;
      setAvatars(avatarRecords); setPersonas(personaPayload.personas ?? []); setTools(toolRecords.filter((tool) => tool.enabled)); setKnowledge(knowledgePayload.documents ?? []); setResourcesLoading(false);
    }).catch((cause) => { if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : "角色资源读取失败"); setResourcesLoading(false); } });
    return () => controller.abort();
  }, [resourceRevision]);

  useEffect(() => {
    if (!latestResource) return;
    if (latestResource.kind === "avatar") {
      setDraft((current) => ({ ...current, avatarId: latestResource.id, actionId: null, talkingVariantId: null }));
      setOpenModule("avatar");
      setNotice("新形象已创建并选中");
    } else if (latestResource.kind === "action") {
      setDraft((current) => ({ ...current, actionId: latestResource.id, talkingVariantId: null }));
      setOpenModule("action");
      setNotice("新动作已创建并选中");
    }
  }, [latestResource]);

  useEffect(() => {
    if (!draftReady || resourcesLoading || !avatars.length) return;
    try {
      const snapshot = JSON.parse(window.sessionStorage.getItem(RESOURCE_RETURN_KEY) ?? "null") as { avatars?: string[]; actions?: string[]; variants?: string[] } | null;
      if (!snapshot) return;
      const addedAvatar = avatars.find((item) => !snapshot.avatars?.includes(item.avatar_id));
      const selectedAvatar = addedAvatar ?? avatars.find((item) => item.avatar_id === draft.avatarId) ?? null;
      const addedAction = selectedAvatar?.actions.find((item) => !item.deleted_at && item.video_url && !snapshot.actions?.includes(item.avatar_action_id));
      const selectedAction = addedAction ?? selectedAvatar?.actions.find((item) => item.avatar_action_id === draft.actionId) ?? null;
      const addedVariant = selectedAction?.talking_variants?.find((item) => !item.deleted_at && item.video_url && !snapshot.variants?.includes(item.id));
      if (addedAvatar || addedAction || addedVariant) {
        setDraft((current) => ({ ...current, avatarId: selectedAvatar?.avatar_id ?? current.avatarId,
          actionId: selectedAction?.avatar_action_id ?? current.actionId, talkingVariantId: addedVariant?.id ?? current.talkingVariantId }));
        setNotice("新建素材已带回创建流程，请确认当前选择");
      }
      window.sessionStorage.removeItem(RESOURCE_RETURN_KEY);
    } catch { window.sessionStorage.removeItem(RESOURCE_RETURN_KEY); }
  }, [avatars, draft.actionId, draft.avatarId, draft.talkingVariantId, draftReady, resourcesLoading]);

  const needsAvatar = draft.modes.some((mode) => mode !== "conversation");
  const needsRealtime = draft.modes.includes("realtime");
  const needsAction = draft.modes.includes("offline") || draft.modes.includes("lip-sync");
  const needsTalking = draft.modes.includes("offline");
  const avatar = avatars.find((item) => item.avatar_id === draft.avatarId) ?? null;
  const actions = useMemo(() => avatar?.actions.filter((item) => !item.deleted_at && item.video_url) ?? [], [avatar]);
  const action = actions.find((item) => item.avatar_action_id === draft.actionId) ?? null;
  const talkingVariants = action?.talking_variants?.filter((item) => item.method === "lipforcing" && !item.deleted_at && item.video_url && item.source_video_url === action.video_url) ?? [];
  const talkingVariant = talkingVariants.find((item) => item.id === draft.talkingVariantId) ?? null;
  const realtimeReady = avatar?.realtime_binding?.state === "accepted";
  const foundationReady = Boolean(draft.name.trim());
  const modesReady = draft.modes.length > 0;
  const avatarReady = !needsAvatar || Boolean(avatar);
  const actionReady = !needsAction || Boolean(action);
  const talkingReady = !needsTalking || Boolean(talkingVariant);
  const allReady = foundationReady && modesReady && avatarReady && (!needsRealtime || realtimeReady) && actionReady && talkingReady && (!draft.modes.includes("lip-sync") || advancedModeReady);
  const visibleSteps = ["foundation", "modes", ...(needsAvatar ? ["avatar"] : []), ...(needsRealtime ? ["realtime"] : []), ...(needsAction ? ["action"] : []), ...(needsTalking ? ["talking"] : [])];
  const completedSteps = [foundationReady, modesReady, avatarReady && needsAvatar, realtimeReady && needsRealtime, actionReady && needsAction, talkingReady && needsTalking].filter(Boolean).length;
  const persona = personas.find((item) => item.personaId === draft.personaId) ?? null;
  const voiceProviderLabel = TTS_PROVIDER_OPTIONS.find((item) => item.value === draft.voiceProvider)?.label ?? draft.voiceProvider;
  const voiceLabel = describeVoiceSelection({ provider: draft.voiceProvider, voice: draft.voiceId, dialect: draft.voiceDialect });
  const previewVideoUrl = draft.defaultMode === "realtime" ? avatar?.realtime_binding?.preview_video_url
    : draft.defaultMode === "offline" ? talkingVariant?.video_url : draft.defaultMode === "lip-sync" ? action?.video_url : undefined;
  const showAvatarPreview = draft.defaultMode !== "conversation" && Boolean(avatar);

  function updateDraft(update: Partial<DraftState>) { setDraft((current) => ({ ...current, ...update })); setError(""); }
  function toggleMode(mode: CreateMode) {
    const selected = draft.modes.includes(mode); if (selected && draft.modes.length === 1) return;
    const modes = selected ? draft.modes.filter((item) => item !== mode) : CREATE_MODES.filter((item) => item === mode || draft.modes.includes(item));
    const defaultMode = !selected && mode === "offline" && draft.defaultMode === "conversation"
      ? "offline"
      : modes.includes(draft.defaultMode) ? draft.defaultMode : preferredRoleMode(modes) as CreateMode;
    updateDraft({ modes, defaultMode });
  }
  function selectAvatar(avatarId: string) { updateDraft({ avatarId, actionId: null, talkingVariantId: null }); setOpenModule(null); }
  function selectAction(actionId: string) {
    const next = actions.find((item) => item.avatar_action_id === actionId);
    const variant = next?.talking_variants?.find((item) => item.method === "lipforcing" && !item.deleted_at && item.video_url && item.source_video_url === next.video_url);
    updateDraft({ actionId, talkingVariantId: variant?.id ?? null });
    setOpenModule(null);
  }
  function rememberResources() {
    window.sessionStorage.setItem(RESOURCE_RETURN_KEY, JSON.stringify({ avatars: avatars.map((item) => item.avatar_id),
      actions: avatars.flatMap((item) => item.actions.map((asset) => asset.avatar_action_id)),
      variants: avatars.flatMap((item) => item.actions.flatMap((asset) => (asset.talking_variants ?? []).map((variant) => variant.id))) }));
  }
  function saveDraftNotice() { window.sessionStorage.setItem(ROLE_CREATE_DRAFT_KEY, JSON.stringify(draft)); setNotice("草稿已保存到当前浏览器"); }
  async function submit() {
    if (!allReady || busy) return; setBusy(true); setError(""); setNotice("");
    try {
      const role = await createRole({ displayName: draft.name.trim(), voiceProvider: draft.voiceProvider, voiceId: draft.voiceId, voiceDialect: draft.voiceDialect,
        asrProvider: draft.asrProvider, llmProvider: draft.llmProvider,
        personaId: draft.personaId, avatarId: draft.avatarId, enabledModes: draft.modes, defaultMode: draft.defaultMode,
        defaultSelections: { ...(draft.actionId ? { "lip-sync": { action_id: draft.actionId } } : {}),
          ...(draft.actionId && draft.talkingVariantId ? { offline: { action_id: draft.actionId, talking_variant_id: draft.talkingVariantId } } : {}) },
        memoryEnabled: draft.memoryEnabled, toolIds: draft.toolIds });
      if (draft.voiceConfigurationTarget) {
        const response = await fetch(`/api/user/role-tts-selections/${encodeURIComponent(role.role_id)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: draft.voiceConfigurationTarget }),
        });
        if (!response.ok) {
          window.sessionStorage.setItem("openrealtime:role-create-notice", "角色已创建，但语音配置未能绑定；请在角色设置里重新选择。");
          window.sessionStorage.removeItem(ROLE_CREATE_DRAFT_KEY); window.sessionStorage.removeItem(RESOURCE_RETURN_KEY);
          router.replace(`/roles/${encodeURIComponent(role.role_id)}`);
          return;
        }
      }
      if (draft.knowledgeIds.length) {
        const response = await fetch(`/api/knowledge/bindings/${encodeURIComponent(role.role_id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ documentIds: draft.knowledgeIds }) });
        const payload = await readJsonResponse<{ documentIds?: string[]; error?: string }>(response, "知识库绑定失败");
        if (!response.ok || !payload.documentIds) {
          window.sessionStorage.setItem("openrealtime:role-create-notice", payload.error || "角色已创建，但知识库绑定失败，请在角色配置中重试");
          window.sessionStorage.removeItem(ROLE_CREATE_DRAFT_KEY); window.sessionStorage.removeItem(RESOURCE_RETURN_KEY);
          router.replace(`/roles/${encodeURIComponent(role.role_id)}`);
          return;
        }
      }
      window.sessionStorage.removeItem(ROLE_CREATE_DRAFT_KEY); window.sessionStorage.removeItem(RESOURCE_RETURN_KEY); router.replace(`/roles/${encodeURIComponent(role.role_id)}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "角色创建失败"); setBusy(false); }
  }
  function startResize(event: ReactPointerEvent<HTMLDivElement>) { resizeRef.current = { pointerId: event.pointerId, startX: event.clientX, width: panelWidth }; event.currentTarget.setPointerCapture(event.pointerId); }
  function resize(event: ReactPointerEvent<HTMLDivElement>) { if (resizeRef.current?.pointerId === event.pointerId) setPanelWidth(Math.min(640, Math.max(420, resizeRef.current.width + resizeRef.current.startX - event.clientX))); }
  function stopResize(event: ReactPointerEvent<HTMLDivElement>) { if (resizeRef.current?.pointerId === event.pointerId) { resizeRef.current = null; event.currentTarget.releasePointerCapture(event.pointerId); } }
  const status = (module: ModuleId) => module === "foundation" ? foundationReady ? "已完成" : "待配置" : module === "modes" ? modesReady ? `已选 ${draft.modes.length} 项` : "待配置" : module === "avatar" ? avatar ? "已完成" : "待配置" : module === "realtime" ? realtimeReady ? "已完成" : "待配置" : module === "action" ? action ? "已完成" : "待配置" : talkingVariant ? "已完成" : "待配置";
  const done = (module: ModuleId) => status(module) === "已完成" || module === "modes" && modesReady;
  const incompleteSteps: Array<{ id: ModuleId; label: string }> = [
    ...(!foundationReady ? [{ id: "foundation" as const, label: "角色名称" }] : []),
    ...(!modesReady ? [{ id: "modes" as const, label: "呈现模式" }] : []),
    ...(needsAvatar && !avatar ? [{ id: "avatar" as const, label: "数字人形象" }] : []),
    ...(needsRealtime && !realtimeReady ? [{ id: "realtime" as const, label: "实时驱动" }] : []),
    ...(needsAction && !action ? [{ id: "action" as const, label: "动作底片" }] : []),
    ...(needsTalking && !talkingVariant ? [{ id: "talking" as const, label: "口型对齐" }] : []),
  ];
  function handleCreateAction() {
    if (allReady) void submit();
    else setOpenModule(incompleteSteps[0]?.id ?? "foundation");
  }
  const actionHref = avatar ? `/roles/new/action?avatar_id=${encodeURIComponent(avatar.avatar_id)}` : "/roles/new";
  const talkingHref = avatar && action
    ? avatar.avatar_id.startsWith("avatar-personal-")
      ? `/services/talking?avatar_id=${encodeURIComponent(avatar.avatar_id)}&action_id=${encodeURIComponent(action.avatar_action_id)}&return_to=role-create&method=lipforcing`
      : `/avatars/create?task=lightweight&method=lipforcing&avatar_id=${encodeURIComponent(avatar.avatar_id)}&avatar_action_id=${encodeURIComponent(action.avatar_action_id)}&return_to=role-create`
    : "/roles/new";

  return <main className={styles.workbench} style={{ "--create-panel-width": `${panelWidth}px` } as CSSProperties}>
    <div className={styles.stage} aria-live="polite">{previewVideoUrl ? <><video className={styles.stageBackdrop} src={previewVideoUrl} autoPlay muted loop playsInline aria-hidden="true" /><video className={styles.stageMedia} src={previewVideoUrl} autoPlay muted loop playsInline aria-label={`${draft.name || "新角色"}素材预览`} /></> : showAvatarPreview && avatar ? <><Image className={styles.stageBackdrop} src={avatar.source_image_url} alt="" fill priority sizes="100vw" unoptimized /><Image className={styles.stageMedia} src={avatar.source_image_url} alt={`${avatar.display_name}数字人预览`} fill priority sizes="100vw" unoptimized /></> : <div className={styles.orbStage}><i /><i /><MessageCircle /></div>}<div className={styles.stageWash} /><div className={styles.stageCopy}><span><i />{ROLE_MODE_LABELS[draft.defaultMode]}</span><h1>{draft.name.trim() || "未命名角色"}</h1><p>{persona?.personaName ?? "通用助手"}</p></div></div>
    <header className={styles.topbar}><Link href="/roles" aria-label="返回角色列表"><ArrowLeft /></Link><div><span>CREATE ROLE</span><strong>创建角色</strong></div><button type="button" onClick={saveDraftNotice}><Save />保存草稿</button></header>
    <aside className={styles.panel} aria-label="角色创建任务"><div className={styles.resizeHandle} role="separator" aria-label="调整创建窗口宽度" aria-orientation="vertical" onPointerDown={startResize} onPointerMove={resize} onPointerUp={stopResize} onPointerCancel={stopResize}><span /></div><header className={styles.panelHeader}><div><small>DYNAMIC SETUP</small><h2>创建任务</h2><p>选择模式后，只显示实际需要完成的步骤。</p></div><span><strong>{completedSteps}</strong> / {visibleSteps.length}</span></header><div className={styles.panelBody}>
      <TaskModule id="foundation" icon={<Sparkles />} title="角色基础" detail={draft.name.trim() || "名称、声音与能力"} openModule={openModule} status={status("foundation")} done={done("foundation")} onOpen={setOpenModule}><div className={styles.foundationGrid}>
        <label className={styles.field}><span>角色名称</span><input autoFocus maxLength={80} value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} placeholder="例如：产品顾问" /></label>
        <BaseSetting id="voice" icon={<Volume2 />} title="声音" detail={`${voiceProviderLabel} · ${voiceLabel}`} openSetting={openBaseSetting} onOpen={setOpenBaseSetting}><VoiceSelector showCurrent={false} value={{ provider: draft.voiceProvider, voice: draft.voiceId, dialect: draft.voiceDialect }} configurationTarget={draft.voiceConfigurationTarget} onConfigurationChange={(target) => updateDraft({ voiceConfigurationTarget: target, voiceCustomized: true })} onChange={(voice) => updateDraft({ voiceProvider: voice.provider, voiceId: voice.voice, voiceDialect: voice.dialect, voiceCustomized: true })} onSelectionCommit={() => setOpenBaseSetting(null)} allowClone allowManagement /></BaseSetting>
        <BaseSetting id="persona" icon={<UserRound />} title="Persona" detail={persona ? `${persona.personaName} · ${persona.intro || "暂无简介"}` : "默认助手"} openSetting={openBaseSetting} onOpen={setOpenBaseSetting}><div className={styles.optionList}><button type="button" data-selected={!draft.personaId} onClick={() => { updateDraft({ personaId: null }); setOpenBaseSetting(null); }}><span><strong>默认助手</strong><small>使用角色默认对话风格</small></span>{!draft.personaId ? <Check /> : null}</button>{personas.map((item) => <button type="button" data-selected={draft.personaId === item.personaId} key={item.personaId} onClick={() => { updateDraft({ personaId: item.personaId }); setOpenBaseSetting(null); }}><span><strong>{item.personaName}</strong><small>{item.intro || "暂无简介"}</small></span>{draft.personaId === item.personaId ? <Check /> : null}</button>)}</div></BaseSetting>
        <BaseSetting id="tools" icon={<Wrench />} title="工具" detail={draft.toolIds.length ? `已选择 ${draft.toolIds.length} 个` : "暂未选择"} openSetting={openBaseSetting} onOpen={setOpenBaseSetting}><div className={styles.checkList}>{tools.length ? tools.map((tool) => <label key={tool.tool_id}><input type="checkbox" checked={draft.toolIds.includes(tool.tool_id)} onChange={(event) => updateDraft({ toolIds: event.target.checked ? [...draft.toolIds, tool.tool_id] : draft.toolIds.filter((id) => id !== tool.tool_id) })} /><span><strong>{tool.display_name}</strong><small>{tool.builtin ? "内置" : tool.public_enabled ? "共享" : "个人"} · {tool.description}</small></span></label>) : <p className={styles.emptyInline}>暂无可用工具</p>}</div><div className={styles.settingActions}><button type="button" onClick={() => setOpenBaseSetting(null)}>完成选择</button></div></BaseSetting>
        <BaseSetting id="knowledge" icon={<BookOpen />} title="知识库" detail={draft.knowledgeIds.length ? `已选择 ${draft.knowledgeIds.length} 份` : "暂未选择"} openSetting={openBaseSetting} onOpen={setOpenBaseSetting}><div className={styles.checkList}>{knowledge.length ? knowledge.map((doc) => <label key={doc.document_id}><input type="checkbox" checked={draft.knowledgeIds.includes(doc.document_id)} onChange={(event) => updateDraft({ knowledgeIds: event.target.checked ? [...draft.knowledgeIds, doc.document_id] : draft.knowledgeIds.filter((id) => id !== doc.document_id) })} /><span><strong>{doc.title}</strong><small>{doc.owner_id === null ? "共享资料" : "个人资料"}</small></span></label>) : <p className={styles.emptyInline}>暂无可用知识库</p>}</div><div className={styles.settingActions}><button type="button" onClick={() => setOpenBaseSetting(null)}>完成选择</button></div></BaseSetting>
        <button className={styles.memoryButton} type="button" aria-pressed={draft.memoryEnabled} data-selected={draft.memoryEnabled} onClick={() => updateDraft({ memoryEnabled: !draft.memoryEnabled })}><MemoryStick /><span><strong>长期记忆</strong><small>按当前用户和角色隔离保存</small></span><em>{draft.memoryEnabled ? "已启用" : "未启用"}</em></button>
        <details className={styles.advancedProviders}><summary>高级配置</summary><p>未选择时使用“供应商”中的默认配置。</p>
          <label className={styles.field}><span>ASR 供应商</span><SelectMenu fullWidth value={String(draft.asrProvider ?? "")} ariaLabel="角色 ASR 供应商" options={[{ value: "", label: "使用供应商默认配置" }, ...(PROVIDER_CATALOG.asr.map((provider) => ({ value: String(provider.id), label: String(provider.name) })))]} onChange={value => updateDraft({ asrProvider: value as DraftState["asrProvider"] || null })} /></label>
          <label className={styles.field}><span>LLM 供应商</span><SelectMenu fullWidth value={String(draft.llmProvider ?? "")} ariaLabel="角色 LLM 供应商" options={[{ value: "", label: "使用供应商默认配置" }, ...(PROVIDER_CATALOG.llm.map((provider) => ({ value: String(provider.id), label: String(provider.name) })))]} onChange={value => updateDraft({ llmProvider: value as DraftState["llmProvider"] || null })} /></label>
        </details>
        <div className={styles.moduleActions}><button type="button" disabled={!foundationReady} onClick={() => setOpenModule(null)}>完成基础设置</button></div>
      </div></TaskModule>
      <TaskModule id="modes" icon={<MessageCircle />} title="呈现模式" detail={draft.modes.map((mode) => MODE_COPY[mode].title).join("、")} openModule={openModule} status={status("modes")} done={done("modes")} onOpen={setOpenModule}><div className={styles.modeList}>{CREATE_MODES.filter((mode) => mode !== "lip-sync").map((mode) => <button key={mode} type="button" aria-pressed={draft.modes.includes(mode)} data-selected={draft.modes.includes(mode)} onClick={() => toggleMode(mode)}><span>{draft.modes.includes(mode) ? <Check /> : null}</span><div><strong>{MODE_COPY[mode].title}</strong><small>{MODE_COPY[mode].description}</small></div></button>)}{advancedModeReady ? <details><summary>高级模式</summary><button type="button" aria-pressed={draft.modes.includes("lip-sync")} data-selected={draft.modes.includes("lip-sync")} onClick={() => toggleMode("lip-sync")}><span>{draft.modes.includes("lip-sync") ? <Check /> : null}</span><div><strong>{MODE_COPY["lip-sync"].title}</strong><small>{MODE_COPY["lip-sync"].description}</small></div></button></details> : null}</div><label className={`${styles.field} ${styles.defaultModeField}`}><span>默认模式</span><SelectMenu fullWidth value={String(draft.defaultMode)} ariaLabel="默认模式" options={[...(draft.modes.map((mode) => ({ value: String(mode), label: String(MODE_COPY[mode].title) })))]} onChange={value => updateDraft({ defaultMode: value as CreateMode })} /></label><div className={styles.moduleActions}><button type="button" onClick={() => setOpenModule(null)}>完成选择</button></div></TaskModule>
      {needsAvatar ? <TaskModule id="avatar" icon={<UserRound />} title="数字人形象" detail={avatar?.display_name ?? "数字人模式共享同一形象"} openModule={openModule} status={status("avatar")} done={done("avatar")} onOpen={setOpenModule}>{resourcesLoading ? <p className={styles.loading}><LoaderCircle />正在读取数字人形象</p> : <AvatarChoiceGrid avatars={avatars} value={draft.avatarId} onChange={selectAvatar} />}<div className={styles.moduleActions}><Link href="/roles/new/avatar"><Upload />新建形象</Link></div></TaskModule> : null}
      {needsRealtime ? <TaskModule id="realtime" icon={<Radio />} title="实时驱动" detail={realtimeReady ? "当前形象已确认实时效果" : "需要创建并确认实时托管效果"} openModule={openModule} status={status("realtime")} done={done("realtime")} onOpen={setOpenModule}>{avatar ? <div className={styles.requirementState} data-ready={realtimeReady}><span>{realtimeReady ? <Check /> : <Radio />}</span><div><strong>{realtimeReady ? "实时驱动已可用" : "尚未确认实时驱动"}</strong><small>{realtimeReady ? "可以作为角色的实时呈现方式" : "进入创建工具，完成预览并确认后返回"}</small></div></div> : <p className={styles.emptyHint}>请先完成数字人形象步骤。</p>}<div className={styles.moduleActions}>{avatar ? <Link href={`/avatars/create?task=realtime&avatar_id=${encodeURIComponent(avatar.avatar_id)}&return_to=role-create`} onClick={rememberResources}><Radio />{realtimeReady ? "重新配置" : "配置实时驱动"}</Link> : null}</div></TaskModule> : null}
      {needsAction ? <TaskModule id="action" icon={<Film />} title="动作底片" detail={action?.display_name ?? "离线与离线加口型共用"} openModule={openModule} status={status("action")} done={done("action")} onOpen={setOpenModule}>{avatar ? <><div className={styles.actionCardGrid}>{actions.map((item) => {
        const selected = draft.actionId === item.avatar_action_id;
        const talkingCount = item.talking_variants?.filter((variant) => !variant.deleted_at && variant.video_url).length ?? 0;
        return <button className={styles.actionCard} type="button" key={item.avatar_action_id} aria-label={`选择动作 ${item.display_name}`} aria-pressed={selected} data-selected={selected} onClick={() => selectAction(item.avatar_action_id)}><span className={styles.actionCardMedia}><AutoplayPreviewVideo sources={avatarActionPreviewSources(avatar.avatar_id, item)} poster={avatar.source_image_url} />{selected ? <i><Check /></i> : null}</span><span className={styles.actionCardCopy}><strong>{item.display_name}</strong><small>{talkingCount ? `${talkingCount} 个口型对齐` : "动作底片"}</small></span></button>;
      })}<Link className={styles.newActionCard} href={actionHref} aria-label="新建动作"><span><Plus /></span><strong>新建动作</strong><small>上传或生成新的动作底片</small></Link></div>{actions.length ? null : <p className={styles.actionEmptyHint}>当前形象还没有动作底片，从这里创建第一个动作。</p>}</> : <p className={styles.emptyHint}>请先完成数字人形象步骤。</p>}</TaskModule> : null}
      {needsTalking ? <TaskModule id="talking" icon={<Volume2 />} title="口型对齐" detail={talkingVariant?.display_name ?? "离线模式需要与动作配对"} openModule={openModule} status={status("talking")} done={done("talking")} onOpen={setOpenModule}>{avatar && action ? <><div className={styles.actionCardGrid}>{talkingVariants.map((variant) => {
        const selected = draft.talkingVariantId === variant.id;
        return <button className={styles.actionCard} type="button" key={variant.id} aria-label={`选择口型对齐 ${variant.display_name}`} aria-pressed={selected} data-selected={selected} data-media-card-type="talking" onClick={() => { updateDraft({ talkingVariantId: variant.id }); setOpenModule(null); }}><span className={styles.actionCardMedia}><AutoplayPreviewVideo sources={[variant.video_url]} poster={avatar.source_image_url} />{selected ? <i><Check /></i> : null}</span><span className={styles.actionCardCopy}><strong>{variant.display_name}</strong><small>配对动作 · {action.display_name}</small></span></button>;
      })}<Link className={styles.newActionCard} href={talkingHref} aria-label="新建口型对齐" onClick={rememberResources}><span><Plus /></span><strong>新建口型对齐</strong><small>为当前动作生成配对讲话视频</small></Link></div>{talkingVariants.length ? null : <p className={styles.actionEmptyHint}>当前动作还没有口型对齐，从这里创建第一个素材。</p>}</> : <p className={styles.emptyHint}>请先选择动作底片。</p>}</TaskModule> : null}
    </div><footer className={styles.createFooter}><span><small>{allReady ? "配置已就绪" : "还需完成"}</small><strong>{allReady ? `${draft.modes.length} 个模式 · 可以创建角色` : incompleteSteps.map((item) => item.label).join("、")}</strong></span><button className={styles.createButton} type="button" disabled={busy} onClick={handleCreateAction}>{busy ? <LoaderCircle className={styles.spin} /> : <Sparkles />}{busy ? "正在创建…" : "完成创建"}</button></footer></aside>
    <div className={styles.previewDock} aria-label="模式与素材预览"><div className={styles.modeRail}>{draft.modes.map((mode) => <button type="button" key={mode} aria-pressed={draft.defaultMode === mode} data-active={draft.defaultMode === mode} onClick={() => updateDraft({ defaultMode: mode })}>{ROLE_MODE_LABELS[mode]}</button>)}</div><div className={styles.previewMaterial}>{draft.defaultMode !== "conversation" && action ? <><span>{action.video_url ? <video src={action.video_url} muted playsInline preload="metadata" /> : <Film />}</span><small>{draft.defaultMode === "offline" ? talkingVariant?.display_name ?? "待选择口型对齐" : action.display_name}</small></> : <><span><MessageCircle /></span><small>{draft.defaultMode === "conversation" ? "Orb 对话" : needsAction ? "待选择动作" : "数字人预览"}</small></>}</div></div>
    {error ? <p className={styles.floatingError} role="alert">{error}</p> : null}{notice ? <p className={styles.floatingNotice} role="status"><Check />{notice}</p> : null}
  </main>;
}

function AutoplayPreviewVideo({ sources, poster }: { sources: string[]; poster: string }) {
  const sourceKey = sources.join("\n");
  const [sourceIndex, setSourceIndex] = useState(0);
  useEffect(() => setSourceIndex(0), [sourceKey]);
  const source = sources[sourceIndex];
  if (!source) return null;

  return <video
    key={source}
    src={source}
    poster={poster}
    autoPlay
    muted
    loop
    playsInline
    preload="auto"
    data-preview-source-index={sourceIndex}
    aria-hidden="true"
    onCanPlay={(event) => { void event.currentTarget.play().catch(() => undefined); }}
    onError={() => setSourceIndex((current) => current < sources.length - 1 ? current + 1 : current)}
  />;
}

function BaseSetting({ id, icon, title, detail, openSetting, onOpen, children }: { id: BaseSettingId; icon: ReactNode; title: string; detail: string; openSetting: BaseSettingId | null; onOpen: (id: BaseSettingId | null) => void; children: ReactNode }) {
  const open = openSetting === id;
  return <section className={styles.baseSetting} data-open={open}><button className={styles.baseSettingSummary} type="button" aria-expanded={open} onClick={() => onOpen(open ? null : id)}>{icon}<span><strong>{title}</strong><small>{detail}</small></span><ChevronRight /></button>{open ? <div className={styles.baseSettingContent}>{children}</div> : null}</section>;
}

function TaskModule({ id, icon, title, detail, status, done, openModule, onOpen, children }: { id: ModuleId; icon: ReactNode; title: string; detail: string; status: string; done: boolean; openModule: ModuleId | null; onOpen: (id: ModuleId | null) => void; children: ReactNode }) {
  const open = openModule === id;
  return <section className={styles.taskModule} data-open={open} data-done={done}><button className={styles.taskSummary} type="button" aria-expanded={open} onClick={() => onOpen(open ? null : id)}><span className={styles.taskIcon}>{done ? <Check /> : icon}</span><span><strong>{title}</strong><small>{detail}</small></span><em>{status}</em><ChevronDown /></button>{open ? <div className={styles.taskContent}>{children}</div> : null}</section>;
}
