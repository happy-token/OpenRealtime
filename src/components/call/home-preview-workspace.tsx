"use client";

import Image from "next/image";
import Link from "next/link";
import {
  Check,
  FolderOpen,
  UserRound,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { AvatarCapabilityNotice } from "@/components/avatar/avatar-capability-notice";
import { useProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { WorkbenchActionFolder, WorkbenchConversationOption, WorkbenchCreateCard, WorkbenchMediaOption } from "@/components/workspace/workbench-resource-rails";
import { ConversationStartAction } from "./conversation-start-action";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import type { AvatarAction, AvatarAsset } from "@/lib/avatar-catalog";
import { fetchOwnedAvatars, fetchPersonalAvatars } from "@/lib/avatar-catalog-client";
import { loadCurrentAvatarCatalog, loadInternalPresetAvatars } from "@/lib/avatar-library-catalog-client";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord, OwnedAvatarRecord } from "@/lib/avatar-records";
import { avatarPersonaSelectionId } from "@/lib/avatar-persona";
import type { DigitalHumanAssetCatalog } from "@/lib/digital-human-asset-catalog";
import { readJsonResponse } from "@/lib/http-json-response";
import type { RolePresentationMode, RoleRecord } from "@/lib/role-records";
import { getSegmentedAvatarRuntime } from "@/lib/segmented-avatar-runtime";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";
import { activateMacLipSyncRuntime, MAC_LIP_SYNC_RUNTIME_CHOICES } from "@/components/digital-human/segmented-avatar-config";
import {
  type AvatarDisplayConfig,
  type ExperienceMode,
} from "@/components/digital-human/types";
import { useAvatarCapabilities } from "@/hooks/use-avatar-capabilities";
import { useAvatarActionOrder } from "@/hooks/use-avatar-action-order";
import { HomeRoleModeControls } from "./home-role-mode-controls";
import { Orb } from "./orb";
import { PersonaQuickSelect } from "./persona-quick-select";
import { VOICE_VISUAL_THEME_OPTIONS, type VoiceVisualTheme } from "./voice-theme";
import styles from "./preview-workspace-lab.module.css";
import { publishHomeBackdropScene } from "@/components/workspace/home-backdrop";
import type { AvatarWorkbenchLocation } from "@/lib/avatar-workbench-navigation";

type AvatarMode = "offline" | "lip-sync" | "realtime";
type EdgePanel = "visual" | "motion";
type MobileSection = "visual" | "action";

const HOME_AVATAR_MEMORY_KEY = "openrealtime-home-avatar-memory-v1";
const HOME_EDGE_HINT_KEY = "openrealtime-home-edge-hint-v1";

interface HomePreviewWorkspaceProps {
  purpose?: "conversation" | "library";
  role?: RoleRecord | null;
  officialRealtime?: boolean;
  roleMode?: RolePresentationMode;
  configLoading?: boolean;
  configReady?: boolean;
  sessionActive?: boolean;
  connected: boolean;
  error: string | null;
  visualTheme: VoiceVisualTheme;
  experienceMode: ExperienceMode;
  avatarDisplayConfig: AvatarDisplayConfig;
  reducedMotion: boolean;
  onVisualThemeChange: (theme: VoiceVisualTheme) => void;
  onExperienceModeChange: (mode: ExperienceMode) => void;
  onAvatarDisplayConfigChange: (config: AvatarDisplayConfig) => void;
  onStartSession: (mode?: ExperienceMode) => void;
  onRoleSelect?: (role: RoleRecord) => void;
  onRoleModeSelect?: (mode: RolePresentationMode, actionId?: string, talkingVariantId?: string) => Promise<void>;
  onOpenProduction?: (location: AvatarWorkbenchLocation) => void;
  catalogRevision?: number;
  stagePreview?: { url: string; name: string; kind?: "talking" } | null;
  collapseResourceRails?: boolean;
}

export interface HomeAvatarChoice {
  id: string;
  name: string;
  avatarName?: string;
  role: string;
  preview?: string;
  motion?: string;
  providerAvatarId?: string;
  config: AvatarDisplayConfig;
}

interface AvatarMemory {
  modes?: Partial<Record<AvatarMode, AvatarDisplayConfig>>;
  avatars?: Partial<Record<AvatarMode, Record<string, AvatarDisplayConfig>>>;
  variants?: Record<string, string>;
}

const ORB_OPTIONS = VOICE_VISUAL_THEME_OPTIONS;

const HOME_AVATAR_ORDER = [
  "companion",
  "anchor",
  "ancient-beauty",
  "newscaster",
  "office-woman",
  "virtual-idol",
] as const;

export function resolveSegmentedHomePreview(
  previewKind: "motion" | "identity",
  choices: {
    unified?: HomeAvatarChoice;
    motion?: HomeAvatarChoice;
    identity?: HomeAvatarChoice;
    current: HomeAvatarChoice;
  },
): HomeAvatarChoice {
  if (previewKind === "motion") {
    return (choices.unified?.motion ? choices.unified : undefined)
      ?? choices.motion
      ?? choices.unified
      ?? choices.identity
      ?? choices.current;
  }
  return choices.unified ?? choices.identity ?? choices.current;
}

export function buildSegmentedMotionChoices(
  base: AvatarDisplayConfig,
  catalog: DigitalHumanAssetCatalog,
): HomeAvatarChoice[] {
  return catalog.motions
    .filter((asset) => asset.phase === "built-in" || asset.phase === "ready")
    .sort((left, right) => {
      const leftIndex = HOME_AVATAR_ORDER.indexOf(left.visualIdentityId as (typeof HOME_AVATAR_ORDER)[number]);
      const rightIndex = HOME_AVATAR_ORDER.indexOf(right.visualIdentityId as (typeof HOME_AVATAR_ORDER)[number]);
      return (leftIndex < 0 ? HOME_AVATAR_ORDER.length : leftIndex)
        - (rightIndex < 0 ? HOME_AVATAR_ORDER.length : rightIndex);
    })
    .map<HomeAvatarChoice>((asset) => {
      const identity = catalog.identities.find((candidate) => candidate.id === asset.visualIdentityId);
      return {
        id: `segmented-motion:${asset.id}`,
        name: asset.name,
        avatarName: identity?.name ?? asset.visualIdentityId,
        role: "配套动作",
        preview: asset.previewImageUrl ?? identity?.previewImageUrl ?? "",
        motion: asset.videoUrl,
        config: {
          ...base,
          renderPath: "segmented",
          segmentedPresetId: "custom-upload",
          segmentedAvatarId: asset.visualIdentityId,
          segmentedDisplayName: identity?.name ?? asset.visualIdentityId,
          segmentedAvatarActionId: asset.id,
        },
      };
    });
}

export function buildSegmentedIdentityChoices(
  base: AvatarDisplayConfig,
  catalog: DigitalHumanAssetCatalog,
): HomeAvatarChoice[] {
  return catalog.identities.map((asset) => ({
    id: `segmented-identity:${asset.id}`,
    name: asset.name,
    role: "本地形象",
    preview: asset.previewImageUrl,
    config: {
      ...base,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: asset.id,
      segmentedDisplayName: asset.name,
      segmentedAvatarActionId: `builtin:identity-static:${asset.id}`,
    },
  }));
}

export async function readAvatarMutationPayload(response: Response): Promise<{
  avatar?: AnamHostedAvatar;
  error?: string;
}> {
  const payload = await readJsonResponse<unknown>(response, "数字人服务请求失败");
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("数字人服务返回了无法识别的响应");
  }
  return payload as { avatar?: AnamHostedAvatar; error?: string };
}

export function shouldLoadAvatarPreviewDirectly(previewUrl: string) {
  return /^\/api\/avatars\/[^/]+\/image(?:\?|$)/.test(previewUrl);
}

export function resolveMainAvatarMotionFit(videoWidth: number, videoHeight: number): "cover" | "contain" {
  if (videoWidth <= 0 || videoHeight <= 0) return "contain";
  return videoWidth >= videoHeight ? "cover" : "contain";
}

function avatarModeForConfig(config: AvatarDisplayConfig): AvatarMode {
  if (config.renderPath === "orchestrated") return "offline";
  if (config.renderPath === "segmented") return "lip-sync";
  return "realtime";
}

function readAvatarMemory(): AvatarMemory {
  if (typeof window === "undefined") return {};
  try {
    const value = JSON.parse(window.localStorage.getItem(HOME_AVATAR_MEMORY_KEY) ?? "null");
    return value && typeof value === "object" ? value as AvatarMemory : {};
  } catch {
    return {};
  }
}

function writeAvatarMemory(config: AvatarDisplayConfig) {
  if (typeof window === "undefined") return;
  const mode = avatarModeForConfig(config);
  const current = readAvatarMemory();
  const avatarKey = mode === "realtime" ? config.avatarProfileId : config.segmentedAvatarId;
  const variants = { ...(current.variants ?? {}) };
  if (config.motionTalkingVariantId && config.segmentedAvatarActionId) {
    variants[`${config.segmentedAvatarId}:${config.segmentedAvatarActionId}`] = config.motionTalkingVariantId;
  }
  window.localStorage.setItem(HOME_AVATAR_MEMORY_KEY, JSON.stringify({
    modes: { ...(current.modes ?? {}), [mode]: config },
    avatars: {
      ...(current.avatars ?? {}),
      [mode]: { ...(current.avatars?.[mode] ?? {}), [avatarKey]: config },
    },
    variants,
  } satisfies AvatarMemory));
}

function selectableActions(avatar: AvatarAsset | undefined) {
  return avatar?.actions.filter((action) => (
    action.state !== "needs-attention" && Boolean(action.videoUrl)
  )) ?? [];
}

function activeTalkingVariants(action: OwnedAvatarActionRecord | undefined) {
  if (!action?.video_url) return [];
  return (action.talking_variants ?? []).filter((variant) => (
    !variant.deleted_at && variant.source_video_url === action.video_url && Boolean(variant.video_url)
  ));
}

export function resolveSelectedAvatarAction(
  catalogAction: AvatarAction | undefined,
  ownedAction: OwnedAvatarActionRecord | undefined,
): AvatarAction | undefined {
  if (catalogAction?.videoUrl) return catalogAction;
  if (ownedAction?.video_url) {
    return {
      avatarActionId: ownedAction.avatar_action_id,
      displayName: ownedAction.display_name,
      videoUrl: ownedAction.video_url,
      state: "available",
      pendingModelCount: ownedAction.pending_model_count,
    };
  }
  return catalogAction;
}

function pairedActions(avatar: AvatarAsset, ownedAvatar: OwnedAvatarRecord | undefined) {
  return selectableActions(avatar).filter((action) => {
    const ownedAction = ownedAvatar?.actions.find((candidate) => (
      candidate.avatar_action_id === action.avatarActionId && !candidate.deleted_at
    ));
    return activeTalkingVariants(ownedAction).length > 0;
  });
}

function VisualThemePreview({ theme, colors }: { theme: VoiceVisualTheme; colors: readonly string[] }) {
  return (
    <span
      className={styles.orbSwatch}
      data-theme={theme}
      style={{ "--theme-a": colors[0], "--theme-b": colors[1], "--theme-c": colors[2] } as CSSProperties}
      aria-hidden="true"
    >
      <i /><i /><i /><i /><i />
    </span>
  );
}

function MediaOption({
  name,
  eyebrow,
  image,
  video,
  selected,
  axis,
  onSelect,
}: {
  name: string;
  eyebrow: string;
  image?: string;
  video?: string | null;
  selected: boolean;
  axis: "vertical" | "horizontal";
  onSelect: () => void;
}) {
  return <WorkbenchMediaOption name={name} eyebrow={eyebrow} image={image} video={video}
    selected={selected} axis={axis} onSelect={onSelect} />;
}

function LibraryCreateCard({
  kind,
  title,
  note,
  axis,
  onCreate,
}: {
  kind: "avatar" | "motion";
  title: string;
  note: string;
  axis: "vertical" | "horizontal";
  onCreate: () => void;
}) {
  return <WorkbenchCreateCard kind={kind} title={title} note={note} axis={axis} onCreate={onCreate} />;
}

export function ActionMaterialFolder({
  action,
  index,
  image,
  variants,
  selected,
  selectedVariantId,
  open,
  onOpenChange,
  onSelectAction,
  onSelectRuntime,
  runtimeSelected,
  onSelectVariant,
  onCreateTalking,
  previewActive,
  ...pointerHandlers
}: {
  action: AvatarAction;
  index: number;
  image?: string;
  variants: AvatarTalkingVariant[];
  selected: boolean;
  selectedVariantId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelectAction?: () => boolean | void;
  onSelectRuntime?: () => void;
  runtimeSelected?: boolean;
  onSelectVariant: (variantId: string) => void;
  onCreateTalking?: () => void;
  previewActive?: boolean;
  onActionPointerDown?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onActionPointerMove?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onActionPointerUp?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onActionPointerCancel?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
}) {
  return <WorkbenchActionFolder action={action} index={index} image={image} variants={variants}
    selected={selected} selectedVariantId={selectedVariantId} open={open} previewActive={previewActive} {...pointerHandlers}
    onOpenChange={onOpenChange} onSelectAction={onSelectAction} onSelectRuntime={onSelectRuntime} runtimeSelected={runtimeSelected}
    onSelectVariant={onSelectVariant} onCreateTalking={onCreateTalking}
    talkingLabel="口型素材" createLabel="新建口型动作" createNote="新增口型对齐" actionLabel="底片" />;
}

function MainAvatarMotionPreview({ choice }: { choice: HomeAvatarChoice }) {
  const foregroundRef = useRef<HTMLVideoElement>(null);
  const [fit, setFit] = useState<"cover" | "contain">("cover");
  const motion = choice.motion ?? "";
  const ensurePlayback = useCallback(() => {
    if (document.visibilityState === "hidden") return;
    const video = foregroundRef.current;
    if (video?.error) video.load();
    if (video?.paused) void video.play().catch(() => undefined);
  }, []);
  useEffect(() => {
    setFit("cover");
    const frame = window.requestAnimationFrame(ensurePlayback);
    document.addEventListener("visibilitychange", ensurePlayback);
    window.addEventListener("pageshow", ensurePlayback);
    window.addEventListener("focus", ensurePlayback);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", ensurePlayback);
      window.removeEventListener("pageshow", ensurePlayback);
      window.removeEventListener("focus", ensurePlayback);
    };
  }, [ensurePlayback, motion]);
  return <video key={motion} ref={foregroundRef} className={styles.avatarPreviewForeground} data-fit={fit} src={motion} poster={choice.preview} autoPlay loop muted playsInline preload="auto" aria-label={`${choice.avatarName ?? choice.name} 动作预览`} onLoadedMetadata={(event) => setFit(resolveMainAvatarMotionFit(event.currentTarget.videoWidth, event.currentTarget.videoHeight))} onCanPlay={ensurePlayback} />;
}

export function resolveAvatarStagePreviewSource({
  libraryMode,
  avatarMode,
  motionUrl,
  talkingUrl,
  force,
}: {
  libraryMode: boolean;
  avatarMode: "offline" | "lip-sync" | "realtime";
  motionUrl?: string;
  talkingUrl?: string;
  force: "idle" | "talking" | null;
}): { url: string; kind: "motion" | "talking" } | null {
  if (!motionUrl) return null;
  if (talkingUrl && (libraryMode || (avatarMode === "offline" && force === "talking"))) {
    return { url: talkingUrl, kind: "talking" };
  }
  return { url: motionUrl, kind: "motion" };
}

function OfflineMotionPreview({
  choice,
  talkingUrl,
  force,
  libraryMode,
  avatarMode,
}: {
  choice: HomeAvatarChoice;
  talkingUrl: string;
  force: "idle" | "talking" | null;
  libraryMode: boolean;
  avatarMode: AvatarMode;
}) {
  const activeRef = useRef<HTMLVideoElement>(null);
  const [motionFailed, setMotionFailed] = useState(false);
  const [fit, setFit] = useState<"cover" | "contain">("cover");
  const resolvedPreview = resolveAvatarStagePreviewSource({
    libraryMode,
    avatarMode,
    motionUrl: choice.motion,
    talkingUrl,
    force,
  });
  const playingTalking = resolvedPreview?.kind === "talking" || motionFailed;
  const activeUrl = motionFailed ? talkingUrl : (resolvedPreview?.url ?? "");
  const ensureActivePlayback = useCallback(() => {
    if (document.visibilityState === "hidden") return;
    const activeVideo = activeRef.current;
    if (activeVideo?.paused) void activeVideo.play().catch(() => undefined);
  }, []);
  useEffect(() => {
    setFit("cover");
    const frame = window.requestAnimationFrame(ensureActivePlayback);
    document.addEventListener("visibilitychange", ensureActivePlayback);
    window.addEventListener("pageshow", ensureActivePlayback);
    window.addEventListener("focus", ensureActivePlayback);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", ensureActivePlayback);
      window.removeEventListener("pageshow", ensureActivePlayback);
      window.removeEventListener("focus", ensureActivePlayback);
    };
  }, [activeUrl, ensureActivePlayback]);
  return <video key={activeUrl} ref={activeRef} className={styles.avatarPreviewForeground} data-fit={fit} src={activeUrl} poster={choice.preview} autoPlay loop muted playsInline preload="auto" aria-label={`${choice.avatarName ?? choice.name} ${playingTalking ? "口型对齐预览" : "当前动作"}`} onLoadedMetadata={(event) => setFit(resolveMainAvatarMotionFit(event.currentTarget.videoWidth, event.currentTarget.videoHeight))} onCanPlay={ensureActivePlayback} onError={() => setMotionFailed(true)} />;
}

export function HomePreviewWorkspace({
  purpose = "conversation",
  role = null,
  officialRealtime = false,
  roleMode,
  configLoading = false,
  configReady = true,
  sessionActive = false,
  connected,
  error,
  visualTheme,
  experienceMode,
  avatarDisplayConfig,
  reducedMotion,
  onVisualThemeChange,
  onExperienceModeChange,
  onAvatarDisplayConfigChange,
  onStartSession,
  onRoleSelect,
  onRoleModeSelect,
  onOpenProduction,
  catalogRevision = 0,
  stagePreview = null,
  collapseResourceRails = false,
}: HomePreviewWorkspaceProps) {
  const { capabilities, error: capabilityError, retry: retryCapabilities } = useAvatarCapabilities();
  const ensureProviderKey = useProviderKeyGate();
  const [edgePanel, setEdgePanel] = useState<EdgePanel | null>(null);
  const [mobileSection, setMobileSection] = useState<MobileSection>("visual");
  const [expandedActionId, setExpandedActionId] = useState<string | null>(null);
  const [edgeHint, setEdgeHint] = useState(false);
  const [previewEnergy] = useState(42);
  const [panelTransparency, setPanelTransparency] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES.transparency);
  const [panelGlassBlur, setPanelGlassBlur] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES.glassBlur);
  const [hostedAvatars, setHostedAvatars] = useState<AnamHostedAvatar[]>([]);
  const [hostedDefaultAvatarId, setHostedDefaultAvatarId] = useState("");
  const [hostedCatalogNeedsKey, setHostedCatalogNeedsKey] = useState(false);
  const [hostedCatalogError, setHostedCatalogError] = useState("");
  const [avatarCatalog, setAvatarCatalog] = useState<AvatarAsset[]>(() => loadInternalPresetAvatars({ includeLocal: false }));
  const [ownedAvatars, setOwnedAvatars] = useState<OwnedAvatarRecord[]>([]);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  const avatarMode = avatarModeForConfig(avatarDisplayConfig);
  const libraryMode = purpose === "library";

  const cancelEdgeTimers = useCallback(() => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  }, []);

  const cancelEdgeClose = useCallback(() => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }, []);

  const openEdge = useCallback((panel: EdgePanel, section: MobileSection, delayed = false) => {
    cancelEdgeTimers();
    const show = () => {
      setEdgePanel(panel);
      setMobileSection(section);
      if (panel !== "motion") setExpandedActionId(null);
      setEdgeHint(false);
      window.localStorage.setItem(HOME_EDGE_HINT_KEY, "seen");
    };
    if (delayed) openTimer.current = window.setTimeout(show, 150);
    else show();
  }, [cancelEdgeTimers]);

  const scheduleEdgeClose = useCallback(() => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    openTimer.current = null;
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => {
      setEdgePanel(null);
      setExpandedActionId(null);
    }, 350);
  }, []);

  useEffect(() => () => cancelEdgeTimers(), [cancelEdgeTimers]);
  useEffect(() => {
    const saved = readWorkbenchVisualPreferences();
    setPanelTransparency(saved.transparency);
    setPanelGlassBlur(saved.glassBlur);
    if (window.localStorage.getItem(HOME_EDGE_HINT_KEY) === "seen") return;
    setEdgeHint(true);
    const timer = window.setTimeout(() => {
      setEdgeHint(false);
      window.localStorage.setItem(HOME_EDGE_HINT_KEY, "seen");
    }, 1_800);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => writeAvatarMemory(avatarDisplayConfig), [avatarDisplayConfig]);
  useEffect(() => setExpandedActionId(null), [avatarMode, avatarDisplayConfig.segmentedAvatarId]);

  const loadHostedAvatars = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch("/api/anam/avatars", { cache: "no-store", signal });
      const payload = await readJsonResponse<{ avatars?: AnamHostedAvatar[]; defaultAvatarId?: string | null; configured?: boolean; error?: string }>(response, "实时数字人目录读取失败");
      if (!response.ok) {
        setHostedCatalogNeedsKey(payload.configured === false);
        setHostedCatalogError(payload.error ?? "实时数字人目录读取失败");
        return;
      }
      setHostedAvatars(payload.avatars ?? []);
      setHostedDefaultAvatarId(payload.defaultAvatarId ?? "");
      setHostedCatalogNeedsKey(false);
      setHostedCatalogError("");
    } catch (cause) {
      if (!signal?.aborted) setHostedCatalogError(cause instanceof Error ? cause.message : "实时数字人目录读取失败");
    }
  }, []);

  const loadLocalAvatars = useCallback(async (signal?: AbortSignal) => {
    try {
      const [catalog, owned, personal] = await Promise.all([
        loadCurrentAvatarCatalog(signal, { includeHostedAvatars: false, includeOwnedBuiltinActions: true }).catch(() => null),
        fetchOwnedAvatars(signal).catch(() => null),
        fetchPersonalAvatars(signal).catch(() => null),
      ]);
      if (signal?.aborted) return;
      if (catalog) setAvatarCatalog(catalog);
      if (owned || personal) setOwnedAvatars((current) => [
        ...(personal ?? current.filter((item) => item.avatar_id.startsWith("avatar-personal-"))),
        ...(owned ?? current.filter((item) => !item.avatar_id.startsWith("avatar-personal-"))),
      ]);
    } catch {
      // Keep built-ins and the last successful catalog during a transient service failure.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      if (document.visibilityState !== "visible") return;
      if (!libraryMode) void loadHostedAvatars();
      void loadLocalAvatars();
    };
    if (!libraryMode) void loadHostedAvatars(controller.signal);
    void loadLocalAvatars(controller.signal);
    window.addEventListener("focus", refresh);
    window.addEventListener("storage", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      window.removeEventListener("focus", refresh);
      window.removeEventListener("storage", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [catalogRevision, libraryMode, loadHostedAvatars, loadLocalAvatars]);

  const hostedChoices = useMemo<HomeAvatarChoice[]>(() => hostedAvatars.map((avatar) => ({
    id: `hosted:anam:${avatar.id}`,
    name: avatar.displayName,
    role: avatar.origin === "personal" ? "个人形象" : "官方形象",
    preview: avatar.imageUrl,
    providerAvatarId: avatar.id,
    config: {
      ...avatarDisplayConfig,
      renderPath: "hosted",
      provider: "anam",
      avatarProfileId: avatar.id,
      hostedAvatarDisplayName: avatar.displayName,
      hostedAvatarImageUrl: avatar.imageUrl,
    },
  })), [avatarDisplayConfig, hostedAvatars]);

  const segmentedAvatars = useMemo(() => avatarCatalog.flatMap((avatar) => {
    const actions = selectableActions(avatar);
    return avatar.source.kind === "owned" && !avatar.deletedAt && !avatar.avatarId.startsWith("avatar-personal-") && actions.length ? [{ ...avatar, actions }] : [];
  }), [avatarCatalog]);
  const offlineAvatars = useMemo(() => avatarCatalog.flatMap((avatar) => {
    const owned = ownedAvatars.find((candidate) => candidate.avatar_id === avatar.avatarId && !candidate.deleted_at);
    const actions = pairedActions(avatar, owned);
    return avatar.source.kind === "owned" && !avatar.deletedAt && actions.length ? [{ ...avatar, actions }] : [];
  }), [avatarCatalog, ownedAvatars]);
  const libraryAvatars = useMemo(
    () => avatarCatalog.filter((avatar) => !avatar.deletedAt),
    [avatarCatalog],
  );

  const selectedCatalogAvatar = avatarCatalog.find((avatar) => avatar.avatarId === avatarDisplayConfig.segmentedAvatarId);
  const selectedOwnedAvatar = ownedAvatars.find((avatar) => avatar.avatar_id === avatarDisplayConfig.segmentedAvatarId && !avatar.deleted_at);
  const catalogSelectedAction = selectedCatalogAvatar?.actions.find((action) => action.avatarActionId === avatarDisplayConfig.segmentedAvatarActionId);
  const ownedSelectedAction = selectedOwnedAvatar?.actions.find((action) => action.avatar_action_id === avatarDisplayConfig.segmentedAvatarActionId && !action.deleted_at && action.video_url);
  const selectedAction = resolveSelectedAvatarAction(catalogSelectedAction, ownedSelectedAction);
  const selectedOwnedAction = selectedOwnedAvatar?.actions.find((action) => action.avatar_action_id === avatarDisplayConfig.segmentedAvatarActionId && !action.deleted_at);
  const selectedVariants = activeTalkingVariants(selectedOwnedAction);
  const selectedVariant = selectedVariants.find((variant) => variant.id === avatarDisplayConfig.motionTalkingVariantId);

  const currentHostedChoice: HomeAvatarChoice = hostedChoices.find((choice) => choice.config.avatarProfileId === (avatarDisplayConfig.avatarProfileId === "default-anam" ? hostedDefaultAvatarId : avatarDisplayConfig.avatarProfileId)) ?? {
    id: `hosted:${avatarDisplayConfig.provider}:${avatarDisplayConfig.avatarProfileId}`,
    name: avatarDisplayConfig.hostedAvatarDisplayName ?? "当前数字人",
    role: "当前形象",
    preview: avatarDisplayConfig.hostedAvatarImageUrl,
    config: avatarDisplayConfig,
  };
  const selectedAvatarChoice: HomeAvatarChoice = avatarMode === "realtime" ? currentHostedChoice : {
    id: `local:${avatarDisplayConfig.segmentedAvatarId}:${avatarDisplayConfig.segmentedAvatarActionId}`,
    name: selectedAction?.displayName ?? avatarDisplayConfig.segmentedDisplayName ?? "当前数字人",
    avatarName: selectedCatalogAvatar?.displayName ?? selectedOwnedAvatar?.display_name ?? avatarDisplayConfig.segmentedDisplayName,
    role: avatarMode === "offline" ? "动作与口型对齐" : "当前动作",
    preview: selectedCatalogAvatar?.source.imageUrl
      ?? selectedOwnedAvatar?.source_image_url
      ?? (avatarDisplayConfig.segmentedAvatarId.startsWith("avatar-")
        ? `/api/avatars/${encodeURIComponent(avatarDisplayConfig.segmentedAvatarId)}/image`
        : undefined),
    motion: selectedAction?.videoUrl ?? undefined,
    config: avatarDisplayConfig,
  };
  const selectedAvatarName = selectedAvatarChoice.avatarName ?? selectedAvatarChoice.name;
  const cachedAvatarMatchesRole = Boolean(role?.avatar_id
    && role.avatar_id === (avatarDisplayConfig.renderPath === "hosted"
      ? avatarDisplayConfig.avatarProfileId
      : avatarDisplayConfig.segmentedAvatarId));
  const showAvatarPreview = libraryMode || configReady || cachedAvatarMatchesRole;
  const selectedOrb = ORB_OPTIONS.find((option) => option.id === visualTheme) ?? ORB_OPTIONS[0];
  useEffect(() => {
    publishHomeBackdropScene({
      mode: experienceMode,
      image: selectedAvatarChoice.preview,
      theme: visualTheme,
    });
  }, [experienceMode, selectedAvatarChoice.preview, visualTheme]);
  const currentActions = libraryMode
    ? selectableActions(selectedCatalogAvatar)
    : avatarMode === "offline"
    ? (selectedCatalogAvatar && selectedOwnedAvatar ? pairedActions(selectedCatalogAvatar, selectedOwnedAvatar) : [])
    : selectableActions(selectedCatalogAvatar);
  const actionSort = useAvatarActionOrder(avatarDisplayConfig.segmentedAvatarId ?? "", currentActions, (action) => action.avatarActionId);

  const selectedCapability = avatarMode === "realtime" ? capabilities?.anam : avatarMode === "lip-sync" ? capabilities?.localRenderer : capabilities?.assets;
  const capabilityBlocked = experienceMode === "avatar" && selectedCapability?.state !== "available";
  const selectedRuntimeReady = avatarMode === "offline"
    ? Boolean(selectedAction?.videoUrl && selectedVariant?.video_url)
    : avatarMode === "lip-sync"
      ? Boolean(getSegmentedAvatarRuntime(avatarDisplayConfig))
      : Boolean(currentHostedChoice.preview || currentHostedChoice.config.avatarProfileId);

  const applyAvatarConfig = useCallback((config: AvatarDisplayConfig) => {
    writeAvatarMemory(config);
    onAvatarDisplayConfigChange(config);
  }, [onAvatarDisplayConfigChange]);

  function selectLocalAvatar(avatar: AvatarAsset) {
    const remembered = readAvatarMemory().avatars?.[avatarMode]?.[avatar.avatarId];
    if (avatarMode === "lip-sync") {
      const actions = selectableActions(avatar);
      const rememberedAction = actions.find((action) => action.avatarActionId === remembered?.segmentedAvatarActionId);
      const action = rememberedAction ?? actions[0];
      if (!action) return;
      applyAvatarConfig(activateMacLipSyncRuntime({ ...avatarDisplayConfig, renderPath: "segmented", segmentedPresetId: "custom-upload", segmentedAvatarId: avatar.avatarId, segmentedDisplayName: avatar.displayName, segmentedAvatarActionId: action.avatarActionId, motionTalkingVariantId: undefined }, MAC_LIP_SYNC_RUNTIME_CHOICES[0].id));
      return;
    }
    const owned = ownedAvatars.find((candidate) => candidate.avatar_id === avatar.avatarId);
    const actions = pairedActions(avatar, owned);
    const rememberedAction = actions.find((action) => action.avatarActionId === remembered?.segmentedAvatarActionId);
    const action = rememberedAction ?? actions[0];
    const ownedAction = owned?.actions.find((candidate) => candidate.avatar_action_id === action?.avatarActionId);
    const variants = activeTalkingVariants(ownedAction);
    const rememberedVariant = variants.find((variant) => variant.id === remembered?.motionTalkingVariantId);
    const variant = rememberedVariant ?? variants[0];
    if (!action || !variant) return;
    applyAvatarConfig({ ...avatarDisplayConfig, renderPath: "orchestrated", segmentedPresetId: "custom-upload", segmentedAvatarId: avatar.avatarId, segmentedDisplayName: avatar.displayName, segmentedAvatarActionId: action.avatarActionId, motionTalkingVariantId: variant.id });
  }

  function selectLibraryAvatar(avatar: AvatarAsset) {
    const actions = selectableActions(avatar);
    const remembered = readAvatarMemory().avatars?.["lip-sync"]?.[avatar.avatarId];
    const action = actions.find((candidate) => candidate.avatarActionId === remembered?.segmentedAvatarActionId)
      ?? actions[0];
    applyAvatarConfig({
      ...avatarDisplayConfig,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: avatar.avatarId,
      segmentedDisplayName: avatar.displayName,
      segmentedAvatarActionId: action?.avatarActionId ?? `builtin:identity-static:${avatar.avatarId}`,
      motionTalkingVariantId: undefined,
    });
  }

  function selectAction(action: AvatarAction, requestedVariantId?: string) {
    if (libraryMode) {
      applyAvatarConfig({
        ...avatarDisplayConfig,
        renderPath: "segmented",
        segmentedAvatarActionId: action.avatarActionId,
        motionTalkingVariantId: requestedVariantId,
      });
      return;
    }
    if (experienceMode === "voice") onExperienceModeChange("avatar");
    if (requestedVariantId) {
      applyAvatarConfig({
        ...avatarDisplayConfig,
        renderPath: "orchestrated",
        segmentedAvatarActionId: action.avatarActionId,
        motionTalkingVariantId: requestedVariantId,
      });
      return;
    }
    if (avatarMode === "lip-sync") {
      applyAvatarConfig(activateMacLipSyncRuntime({ ...avatarDisplayConfig, renderPath: "segmented", segmentedAvatarActionId: action.avatarActionId, motionTalkingVariantId: undefined }, MAC_LIP_SYNC_RUNTIME_CHOICES[0].id));
      return;
    }
    const ownedAction = selectedOwnedAvatar?.actions.find((candidate) => candidate.avatar_action_id === action.avatarActionId);
    const variants = activeTalkingVariants(ownedAction);
    const rememberedId = readAvatarMemory().variants?.[`${avatarDisplayConfig.segmentedAvatarId}:${action.avatarActionId}`];
    const variant = variants.find((candidate) => candidate.id === requestedVariantId)
      ?? variants.find((candidate) => candidate.id === rememberedId)
      ?? variants[0];
    if (!variant) return;
    applyAvatarConfig({ ...avatarDisplayConfig, renderPath: "orchestrated", segmentedAvatarActionId: action.avatarActionId, motionTalkingVariantId: variant.id });
  }

  function selectRuntimeAction(action: AvatarAction) {
    if (capabilities?.localRenderer.state !== "available") return;
    if (experienceMode === "voice") onExperienceModeChange("avatar");
    applyAvatarConfig(activateMacLipSyncRuntime({
      ...avatarDisplayConfig,
      renderPath: "segmented",
      segmentedAvatarActionId: action.avatarActionId,
      motionTalkingVariantId: undefined,
    }, MAC_LIP_SYNC_RUNTIME_CHOICES[0].id));
  }

  function closePanelsFromBlankPreview(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("button, a, input, textarea, select, aside, [role=dialog], [role=menu]")) return;
    setEdgePanel(null);
    setExpandedActionId(null);
  }

  const visualAvatars: HomeAvatarChoice[] | AvatarAsset[] = avatarMode === "realtime" ? hostedChoices : avatarMode === "offline" ? offlineAvatars : segmentedAvatars;
  const workbenchPersonaAvatarId = avatarPersonaSelectionId({ renderPath: avatarDisplayConfig.renderPath, avatarProfileId: avatarDisplayConfig.avatarProfileId, segmentedAvatarId: avatarDisplayConfig.segmentedAvatarId });
  const panelTokens = workbenchSurfaceTokens({ transparency: panelTransparency, glassBlur: panelGlassBlur });
  const panelStyle = { "--panel-surface-alpha": panelTokens.surfaceAlpha, "--panel-highlight-alpha": panelTokens.highlightAlpha, "--panel-soft-alpha": panelTokens.softAlpha, "--panel-blur": panelTokens.blur } as CSSProperties;
  const visualPanelOpen = edgePanel === "visual" || (libraryMode && !collapseResourceRails);
  const actionPanelOpen = edgePanel === "motion" || (libraryMode && !collapseResourceRails);
  const activeMobileSection = edgePanel ? mobileSection : "visual";

  return (
    <div className={styles.workspace} aria-label={libraryMode ? "数字人资产主页" : undefined} data-purpose={purpose} data-resource-rails-collapsed={collapseResourceRails} data-session-active={sessionActive} data-mode={experienceMode === "voice" ? "orb" : "avatar"} data-orb-theme={visualTheme} data-reduced-motion={reducedMotion} style={panelStyle} onPointerDown={closePanelsFromBlankPreview}>
      <div className={styles.preview} aria-live="polite">
        <div className={styles.atmosphere} aria-hidden="true"><i /><i /><i /></div>
        <div className={styles.orbPreview} data-visible={experienceMode === "voice"}>
          <div className={styles.orbHalo} aria-hidden="true" />
          {experienceMode === "voice" ? <Orb state="listening" level={previewEnergy / 100} theme={visualTheme} /> : null}
        </div>
        {showAvatarPreview && <div className={styles.avatarPreview} data-visible={experienceMode === "avatar"}>
          {experienceMode === "avatar" && stagePreview?.url ? (
            <video key={stagePreview.url} className={styles.avatarPreviewForeground} src={stagePreview.url} autoPlay loop muted playsInline preload="auto" aria-label={`${stagePreview.name} ${stagePreview.kind === "talking" ? "口型动作预览" : "生成动作预览"}`} />
          ) : experienceMode === "avatar" && (libraryMode || avatarMode === "offline") && selectedAvatarChoice.motion && selectedVariant?.video_url ? (
            <OfflineMotionPreview choice={selectedAvatarChoice} talkingUrl={selectedVariant.video_url} force={null} libraryMode={libraryMode} avatarMode={avatarMode} />
          ) : experienceMode === "avatar" && selectedAvatarChoice.motion ? (
            <MainAvatarMotionPreview key={selectedAvatarChoice.id} choice={selectedAvatarChoice} />
          ) : selectedAvatarChoice.preview ? <>
            <Image className={styles.avatarPreviewMotionBackdrop} src={selectedAvatarChoice.preview} alt="" aria-hidden="true" fill sizes="100vw" unoptimized={shouldLoadAvatarPreviewDirectly(selectedAvatarChoice.preview)} />
            <Image className={styles.avatarPreviewForeground} src={selectedAvatarChoice.preview} alt={`${selectedAvatarName} 数字人预览`} fill priority sizes="100vw" unoptimized={shouldLoadAvatarPreviewDirectly(selectedAvatarChoice.preview)} />
          </> : <div className={styles.avatarPreviewPlaceholder}><UserRound aria-hidden="true" /></div>}
          <div className={styles.avatarWash} aria-hidden="true" />
        </div>}
        <div className={styles.previewCopy}>
          <span data-connection={connected || libraryMode ? "ready" : "connecting"} role="status" aria-live="polite"><i />{libraryMode ? "资产预览" : connected ? "预览已就绪" : "语音连接中"}</span>
          <h1>{stagePreview?.name ?? role?.display_name ?? (experienceMode === "voice" ? selectedOrb.name : selectedAvatarName)}</h1>
        </div>
      </div>

      {!libraryMode && !role && !officialRealtime && workbenchPersonaAvatarId ? <div
        className={styles.stageQuickControls}
        aria-label="Persona 快捷配置"
        onPointerDown={() => {
          setEdgePanel(null);
          setExpandedActionId(null);
        }}
      >
        <PersonaQuickSelect avatarId={workbenchPersonaAvatarId} avatarDisplayName={selectedAvatarName} placement="bottom" />
      </div> : null}

      {!libraryMode ? <>
        <ConversationStartAction connected={connected} disabled={configLoading || !configReady || capabilityBlocked || (experienceMode === "avatar" && !selectedRuntimeReady)} ariaLabel="主页开始对话" label={experienceMode === "voice" ? "开始语音对话" : `与 ${role?.display_name ?? selectedAvatarName} 对话`} hint={configLoading ? "正在加载角色" : !configReady ? "角色素材加载失败" : experienceMode === "avatar" && !selectedRuntimeReady ? "当前组合尚不可用" : ""} onPress={() => onStartSession(experienceMode)}>
          {experienceMode === "avatar" ? <AvatarCapabilityNotice capability={selectedCapability} error={capabilityError} onRetry={retryCapabilities} variant="stage" /> : null}
        </ConversationStartAction>
      </> : null}

      {officialRealtime ? null : role && onRoleSelect && onRoleModeSelect ? <HomeRoleModeControls
        role={role}
        mode={roleMode ?? (experienceMode === "voice" ? "conversation" : avatarMode)}
        avatar={ownedAvatars.find((item) => item.avatar_id === role.avatar_id && !item.deleted_at) ?? null}
        config={avatarDisplayConfig}
        canStart={!configLoading && configReady && !capabilityBlocked && (experienceMode === "voice" || selectedRuntimeReady)}
        visualTheme={visualTheme}
        themes={ORB_OPTIONS}
        onVisualThemeChange={onVisualThemeChange}
        onRoleSelect={onRoleSelect}
        onModeSelect={onRoleModeSelect}
        onStart={onStartSession}
        runtimeLipSyncAvailable={capabilities?.localRenderer.state === "available"}
      /> : <div className={styles.edgeControls} data-hint={edgeHint} data-open-panel={edgePanel ?? "none"} onPointerEnter={cancelEdgeClose} onPointerLeave={scheduleEdgeClose}>
        <button className={styles.edgeTrigger} data-library={libraryMode} data-edge="right" type="button" aria-label={experienceMode === "voice" ? "打开视觉主题" : "打开数字人形象"} aria-expanded={visualPanelOpen} onPointerEnter={() => openEdge("visual", "visual", !collapseResourceRails)} onFocus={() => openEdge("visual", "visual")} onClick={() => openEdge("visual", "visual")}><span /></button>
        <button className={styles.edgeTrigger} data-library={libraryMode} data-edge="bottom" type="button" disabled={!libraryMode && experienceMode === "avatar" && avatarMode === "realtime"} aria-label="打开动作列表" aria-expanded={actionPanelOpen} onPointerEnter={() => openEdge("motion", "action", !collapseResourceRails)} onFocus={() => openEdge("motion", "action")} onClick={() => openEdge("motion", "action")}><span /></button>

        <aside className={styles.visualEdgePanel} data-kind={experienceMode === "voice" ? "theme" : "media"} data-open={visualPanelOpen} data-mobile-active={visualPanelOpen && activeMobileSection === "visual"} aria-label={experienceMode === "voice" ? "视觉主题" : "数字人形象"} aria-hidden={collapseResourceRails && !visualPanelOpen} inert={collapseResourceRails && !visualPanelOpen}>
          <header><div><small>{experienceMode === "voice" ? "VISUAL" : "AVATAR"}</small><strong>{experienceMode === "voice" ? "视觉主题" : "形象"}</strong></div>{experienceMode === "avatar" && !libraryMode ? <Link href="/resources?tab=avatars"><FolderOpen aria-hidden="true" /><span>管理</span></Link> : null}</header>
          <div className={styles.visualEdgeList}>
            {experienceMode === "voice" ? ORB_OPTIONS.map((option) => <button className={styles.themeEdgeOption} key={option.id} type="button" data-selected={visualTheme === option.id} aria-pressed={visualTheme === option.id} onClick={() => onVisualThemeChange(option.id)}><VisualThemePreview theme={option.id} colors={option.colors} /><span><strong>{option.name}</strong><small>{option.note}</small></span>{visualTheme === option.id ? <Check aria-hidden="true" /> : null}</button>) : libraryMode ? <>
              <LibraryCreateCard kind="avatar" title="创建形象" note="上传图片" axis="vertical" onCreate={() => onOpenProduction?.({ task: "avatar" })} />
              {libraryAvatars.map((avatar) => <MediaOption key={avatar.avatarId} name={avatar.displayName} eyebrow={avatar.source.kind === "owned" ? "我的形象" : "内置形象"} image={avatar.source.imageUrl} selected={avatarMode !== "realtime" && avatarDisplayConfig.segmentedAvatarId === avatar.avatarId} axis="vertical" onSelect={() => selectLibraryAvatar(avatar)} />)}
            </> : avatarMode === "realtime" ? (visualAvatars as HomeAvatarChoice[]).map((choice) => <MediaOption key={choice.id} name={choice.name} eyebrow="形象" image={choice.preview} selected={avatarDisplayConfig.avatarProfileId === choice.config.avatarProfileId} axis="vertical" onSelect={() => applyAvatarConfig(choice.config)} />) : (visualAvatars as AvatarAsset[]).map((avatar) => <MediaOption key={avatar.avatarId} name={avatar.displayName} eyebrow="形象" image={avatar.source.imageUrl} selected={avatarDisplayConfig.segmentedAvatarId === avatar.avatarId} axis="vertical" onSelect={() => selectLocalAvatar(avatar)} />)}
            {experienceMode === "avatar" && (libraryMode ? libraryAvatars.length === 0 : visualAvatars.length === 0) ? <div className={styles.edgeEmpty}><UserRound aria-hidden="true" /><strong>暂无可运行形象</strong>{libraryMode ? <button type="button" onClick={() => onOpenProduction?.({ task: "avatar" })}>创建第一个形象</button> : <Link href="/resources?tab=avatars">前往资产管理</Link>}</div> : null}
          </div>
        </aside>

        <aside className={styles.actionEdgePanel} data-open={actionPanelOpen} data-folder-open={Boolean(expandedActionId)} data-mobile-active={actionPanelOpen && activeMobileSection === "action"} aria-label="动作" aria-hidden={collapseResourceRails && !actionPanelOpen} inert={collapseResourceRails && !actionPanelOpen}>
          <header><div><strong>动作</strong></div><span>{currentActions.length}</span></header>
          <div className={styles.actionEdgeList}>
            {!libraryMode ? <WorkbenchConversationOption selected={experienceMode === "voice"} onSelect={() => onExperienceModeChange("voice")} /> : null}
            {libraryMode ? <LibraryCreateCard kind="motion" title="创建动作" note="生成动作" axis="horizontal" onCreate={() => onOpenProduction?.({ task: "motion", avatarId: avatarDisplayConfig.segmentedAvatarId })} /> : null}
            {actionSort.orderedActions.map((action, index) => {
              const allVariants = activeTalkingVariants(selectedOwnedAvatar?.actions.find((candidate) => candidate.avatar_action_id === action.avatarActionId));
              const variants = libraryMode ? allVariants : allVariants.filter((variant) => variant.method === "lipforcing");
              return <div className={styles.sortableAction} key={action.avatarActionId} data-action-sort-id={action.avatarActionId} data-open={expandedActionId === action.avatarActionId} data-selected={avatarDisplayConfig.segmentedAvatarActionId === action.avatarActionId} data-dragging={actionSort.draggingActionId === action.avatarActionId} data-drop-target={actionSort.dropActionId === action.avatarActionId}>
              <ActionMaterialFolder
                action={action}
                index={index}
                image={selectedCatalogAvatar?.source.imageUrl}
                variants={variants}
                selected={avatarDisplayConfig.segmentedAvatarActionId === action.avatarActionId}
                selectedVariantId={avatarDisplayConfig.motionTalkingVariantId}
                open={expandedActionId === action.avatarActionId}
                onOpenChange={(open) => setExpandedActionId(open ? action.avatarActionId : null)}
                previewActive={actionPanelOpen}
                {...actionSort.pointerHandlers(action.avatarActionId)}
                onSelectAction={() => { if (actionSort.consumeDragClick()) return false; if (libraryMode) selectAction(action); }}
                onSelectRuntime={!libraryMode && capabilities?.localRenderer.state === "available" ? () => selectRuntimeAction(action) : undefined}
                runtimeSelected={!libraryMode && avatarMode === "lip-sync" && avatarDisplayConfig.segmentedAvatarActionId === action.avatarActionId}
                onSelectVariant={(variantId) => selectAction(action, variantId)}
                onCreateTalking={() => libraryMode ? onOpenProduction?.({ task: "talking", avatarId: avatarDisplayConfig.segmentedAvatarId, actionId: action.avatarActionId }) : window.location.assign(`/resources?tab=avatars&task=talking&avatar_id=${encodeURIComponent(avatarDisplayConfig.segmentedAvatarId)}&action_id=${encodeURIComponent(action.avatarActionId)}`)}
              /></div>;
            })}
          </div>
        </aside>

        {edgePanel || libraryMode ? <div className={styles.mobileEdgeTabs} role="tablist" aria-label="主页配置"><button type="button" role="tab" aria-selected={visualPanelOpen && activeMobileSection === "visual"} onClick={() => openEdge("visual", "visual")}>形象</button>{libraryMode || avatarMode !== "realtime" || experienceMode === "voice" ? <button type="button" role="tab" aria-selected={actionPanelOpen && activeMobileSection === "action"} onClick={() => openEdge("motion", "action")}>动作</button> : null}</div> : null}
      </div>}

      {hostedCatalogNeedsKey && experienceMode === "avatar" && avatarMode === "realtime" ? <button className={styles.catalogRecovery} type="button" onClick={() => void ensureProviderKey("anam").then((ready) => { if (ready) void loadHostedAvatars(); })}>连接 Anam 并读取形象</button> : null}
      {hostedCatalogError && experienceMode === "avatar" && avatarMode === "realtime" ? <p className={styles.homeError} role="alert">{hostedCatalogError}</p> : error ? <p className={styles.homeError} role="alert">{error}</p> : null}
    </div>
  );
}
