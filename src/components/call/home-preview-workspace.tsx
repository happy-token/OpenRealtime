"use client";

import Image from "next/image";
import Link from "next/link";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Film,
  FolderOpen,
  Gauge,
  MessageCircle,
  Maximize2,
  Minimize2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Settings2,
  UserRound,
  Volume2,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import {
  readDigitalHumanAssetCatalog,
  type DigitalHumanAssetCatalog,
} from "@/lib/digital-human-asset-catalog";
import { fetchAvatarActionCatalog, type AvatarActionAsset } from "@/lib/avatar-motion-catalog";
import { getSegmentedAvatarRuntime } from "@/lib/segmented-avatar-runtime";
import { readJsonResponse } from "@/lib/http-json-response";
import { avatarPersonaSelectionId } from "@/lib/avatar-persona";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  workbenchSurfaceTokens,
  writeWorkbenchVisualPreferences,
} from "@/lib/workbench-visual-preferences";
import type { AvatarDisplayConfig, AvatarProvider, ExperienceMode } from "@/components/digital-human/types";
import {
  activateMacLipSyncRuntime,
  MAC_LIP_SYNC_RUNTIME_CHOICES,
} from "@/components/digital-human/segmented-avatar-config";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  findTtsVoice,
  type TtsProvider,
  type TtsVoice,
} from "@/components/drawer/voice-options";
import { VoiceStartButton } from "@/components/ui/voice-start-button";
import { InfoHint } from "@/components/ui/info-hint";
import {
  filterSegmentedAvatarAssets,
  SegmentedAvatarAssetPicker,
} from "@/components/drawer/segmented-avatar-asset-picker";
import type { AvatarAction, AvatarAsset } from "@/lib/avatar-catalog";
import {
  loadCurrentAvatarCatalog,
  loadInternalPresetAvatars,
} from "@/lib/avatar-library-catalog-client";
import { Orb } from "./orb";
import { PersonaQuickSelect } from "./persona-quick-select";
import type { VoiceVisualTheme } from "./voice-theme";
import styles from "./preview-workspace-lab.module.css";

type PanelState = "collapsed" | "compact" | "expanded";
type ConfigTab = "appearance" | "voice" | "model" | "tools" | "conversation" | "general";
export type AdvancedConfigTab = Exclude<ConfigTab, "appearance">;
const IGNORE_MODEL_LABEL_CHANGE: (label: string) => void = () => undefined;

interface HomePreviewWorkspaceProps {
  connected: boolean;
  error: string | null;
  visualTheme: VoiceVisualTheme;
  experienceMode: ExperienceMode;
  avatarDisplayConfig: AvatarDisplayConfig;
  ttsProvider: TtsProvider;
  ttsVoice: TtsVoice;
  reducedMotion: boolean;
  onVisualThemeChange: (theme: VoiceVisualTheme) => void;
  onExperienceModeChange: (mode: ExperienceMode) => void;
  onAvatarDisplayConfigChange: (config: AvatarDisplayConfig) => void;
  settingsRequest: number;
  renderAdvancedSettings: (
    tab: AdvancedConfigTab,
    onVoiceLabelChange: (label: string) => void,
    onModelLabelChange: (label: string) => void,
  ) => ReactNode;
  onStartSession: (mode?: ExperienceMode) => void;
  initialPanelState?: PanelState;
}

interface HomeAvatarChoice {
  id: string;
  name: string;
  avatarName?: string;
  role: string;
  preview?: string;
  motion?: string;
  providerAvatarId?: string;
  config: AvatarDisplayConfig;
}

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

const AVATAR_PROVIDER_OPTIONS: readonly {
  id: AvatarProvider;
  name: string;
  note: string;
  status: string;
}[] = [
  { id: "anam", name: "Anam", note: "实时视频生成", status: "已接入" },
  { id: "heygen", name: "HeyGen", note: "LiveAvatar", status: "待配置" },
  { id: "custom", name: "自定义", note: "私有 Renderer", status: "接口槽位" },
];

const ORB_OPTIONS: readonly {
  id: VoiceVisualTheme;
  name: string;
  note: string;
  colors: readonly string[];
}[] = [
  { id: "liquid-glass", name: "液态玻璃", note: "清透、柔和", colors: ["#f4f7ff", "#8a9cff", "#5de2ff"] },
  { id: "aurora-particles", name: "极光粒子", note: "灵动、有生命力", colors: ["#6bf0d0", "#7567ff", "#d06eff"] },
  { id: "cloud", name: "云雾", note: "自然、安静", colors: ["#ffffff", "#b8c6ff", "#7e8fe6"] },
  { id: "radial", name: "径向脉冲", note: "清晰、有节奏", colors: ["#87e9ff", "#6776ff", "#293164"] },
  { id: "circle", name: "柔和圆形", note: "克制、专注", colors: ["#f4f1ff", "#9fa8ff", "#5969cf"] },
  { id: "bars", name: "音频柱", note: "直观、实时", colors: ["#b7f5ff", "#61a9ff", "#4a52bd"] },
  { id: "debug", name: "调试面板", note: "状态与音量", colors: ["#d8ffe9", "#50c990", "#176052"] },
] as const;

const TAB_ICONS: Record<ConfigTab, LucideIcon> = {
  appearance: Sparkles,
  voice: Volume2,
  model: Bot,
  tools: Wrench,
  conversation: MessageCircle,
  general: Settings2,
};

const AVATAR_ROLE: Record<string, string> = {
  companion: "温柔陪伴",
  anchor: "专业主播",
  "ancient-beauty": "国风知己",
  newscaster: "资讯顾问",
  "office-woman": "商务助理",
  "virtual-idol": "虚拟偶像",
};

const HOME_AVATAR_ORDER = [
  "companion",
  "anchor",
  "ancient-beauty",
  "newscaster",
  "office-woman",
  "virtual-idol",
] as const;

function modeIcon(mode: ExperienceMode) {
  return mode === "voice" ? <Sparkles /> : <UserRound />;
}

function VisualThemePreview({
  theme,
  colors,
}: {
  theme: VoiceVisualTheme;
  colors: readonly string[];
}) {
  return (
    <span
      className={styles.orbSwatch}
      data-theme={theme}
      style={{
        "--theme-a": colors[0],
        "--theme-b": colors[1],
        "--theme-c": colors[2],
      } as CSSProperties}
      aria-hidden="true"
    >
      <i /><i /><i /><i /><i />
    </span>
  );
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
        role: `${AVATAR_ROLE[asset.visualIdentityId] ?? "动态数字人"} · 配套动作`,
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
    role: `${AVATAR_ROLE[asset.id] ?? "本地形象"} · 仅口型`,
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

function hostedChoiceId(config: AvatarDisplayConfig) {
  return `hosted:${config.provider}:${config.avatarProfileId}`;
}

function segmentedMotionChoiceId(config: AvatarDisplayConfig) {
  return config.segmentedAvatarActionId
    ? `segmented-motion:${config.segmentedAvatarActionId}`
    : "";
}

function segmentedIdentityChoiceId(config: AvatarDisplayConfig) {
  return `segmented-identity:${config.segmentedAvatarId}`;
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
  return videoWidth / videoHeight >= 1.2 ? "cover" : "contain";
}

function MainAvatarMotionPreview({ choice }: { choice: HomeAvatarChoice }) {
  const backdropRef = useRef<HTMLVideoElement>(null);
  const foregroundRef = useRef<HTMLVideoElement>(null);
  const [fit, setFit] = useState<"cover" | "contain">("contain");
  const motion = choice.motion ?? "";

  const ensurePlayback = useCallback(() => {
    for (const video of [backdropRef.current, foregroundRef.current]) {
      if (video?.paused) void video.play().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    setFit("contain");
    const frame = window.requestAnimationFrame(ensurePlayback);
    return () => window.cancelAnimationFrame(frame);
  }, [ensurePlayback, motion]);

  return <>
    <video
      ref={backdropRef}
      className={styles.avatarPreviewMotionBackdrop}
      autoPlay
      loop
      muted
      playsInline
      poster={choice.preview}
      aria-hidden="true"
      onCanPlay={ensurePlayback}
    >
      <source src={motion} type="video/mp4" />
    </video>
    <video
      ref={foregroundRef}
      className={styles.avatarPreviewForeground}
      data-fit={fit}
      autoPlay
      loop
      muted
      playsInline
      poster={choice.preview}
      onLoadedMetadata={(event) => {
        setFit(resolveMainAvatarMotionFit(event.currentTarget.videoWidth, event.currentTarget.videoHeight));
        ensurePlayback();
      }}
      onCanPlay={ensurePlayback}
    >
      <source src={motion} type="video/mp4" />
    </video>
  </>;
}

export function HomePreviewWorkspace({
  connected,
  error,
  visualTheme,
  experienceMode,
  avatarDisplayConfig,
  ttsProvider,
  ttsVoice,
  reducedMotion,
  onVisualThemeChange,
  onExperienceModeChange,
  onAvatarDisplayConfigChange,
  settingsRequest,
  renderAdvancedSettings,
  onStartSession,
  initialPanelState = "collapsed",
}: HomePreviewWorkspaceProps) {
  const [panelState, setPanelState] = useState<PanelState>(initialPanelState);
  const [activeTab, setActiveTab] = useState<ConfigTab>("appearance");
  const [previewEnergy, setPreviewEnergy] = useState(42);
  const [panelTransparency, setPanelTransparency] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES.transparency);
  const [panelGlassBlur, setPanelGlassBlur] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES.glassBlur);
  const defaultVoiceLabel = ttsProvider === "bailian"
    ? BAILIAN_CLONED_VOICE_OPTIONS[0].label
    : findTtsVoice(ttsVoice)?.label ?? "当前音色";
  const [selectedVoiceLabel, setSelectedVoiceLabel] = useState(defaultVoiceLabel);
  const [hostedAvatars, setHostedAvatars] = useState<AnamHostedAvatar[]>([]);
  const [hostedDefaultAvatarId, setHostedDefaultAvatarId] = useState("");
  const [hostedCatalogSyncing, setHostedCatalogSyncing] = useState(false);
  const [officialAvatarsExpanded, setOfficialAvatarsExpanded] = useState(false);
  const hostedCatalogSyncId = useRef(0);
  const [renameTarget, setRenameTarget] = useState<HomeAvatarChoice | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState("");
  const [renamingAvatar, setRenamingAvatar] = useState(false);
  const [segmentedPreviewKind, setSegmentedPreviewKind] = useState<"motion" | "identity">("motion");
  const [savedMotionAssets, setSavedMotionAssets] = useState<AvatarActionAsset[]>([]);
  const [segmentedAvatarCatalog, setSegmentedAvatarCatalog] = useState<AvatarAsset[]>(loadInternalPresetAvatars);
  const [assetCatalogHydrated, setAssetCatalogHydrated] = useState(false);
  const [assetCatalogRevision, setAssetCatalogRevision] = useState(0);
  const segmentedCatalogSyncId = useRef(0);
  const unifiedAvatarCatalogSyncId = useRef(0);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!settingsRequest) return;
    setActiveTab("general");
    setPanelState("expanded");
  }, [settingsRequest]);

  useEffect(() => {
    setSelectedVoiceLabel(defaultVoiceLabel);
  }, [defaultVoiceLabel]);

  useEffect(() => {
    const saved = readWorkbenchVisualPreferences();
    setPanelTransparency(saved.transparency);
    setPanelGlassBlur(saved.glassBlur);
  }, []);

  const loadHostedAvatars = useCallback(async (signal?: AbortSignal) => {
    const syncId = ++hostedCatalogSyncId.current;
    setHostedCatalogSyncing(true);
    try {
      const response = await fetch("/api/anam/avatars", { cache: "no-store", signal });
      const payload = await response.json() as {
        avatars?: AnamHostedAvatar[];
        defaultAvatarId?: string | null;
      };
      if (response.ok && !signal?.aborted && syncId === hostedCatalogSyncId.current) {
        setHostedAvatars(payload.avatars ?? []);
        setHostedDefaultAvatarId(payload.defaultAvatarId ?? "");
      }
    } catch {
      // Keep the last successful catalog when the hosted provider is temporarily offline.
    } finally {
      if (!signal?.aborted && syncId === hostedCatalogSyncId.current) setHostedCatalogSyncing(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const syncWhenVisible = () => {
      if (document.visibilityState === "visible") void loadHostedAvatars();
    };
    void loadHostedAvatars(controller.signal);
    window.addEventListener("focus", syncWhenVisible);
    document.addEventListener("visibilitychange", syncWhenVisible);
    return () => {
      controller.abort();
      window.removeEventListener("focus", syncWhenVisible);
      document.removeEventListener("visibilitychange", syncWhenVisible);
    };
  }, [loadHostedAvatars]);

  const loadSegmentedAssets = useCallback(async (signal?: AbortSignal) => {
    const syncId = ++segmentedCatalogSyncId.current;
    try {
      const catalog = await fetchAvatarActionCatalog(undefined, fetch, signal);
      if (!signal?.aborted && syncId === segmentedCatalogSyncId.current) {
        setSavedMotionAssets(catalog.avatarActions);
      }
    } catch {
      // Keep the last successful asset catalog when the local asset service is unavailable.
    }
  }, []);

  const loadUnifiedAvatarCatalog = useCallback(async (signal?: AbortSignal) => {
    const syncId = ++unifiedAvatarCatalogSyncId.current;
    try {
      const catalog = await loadCurrentAvatarCatalog(signal, {
        includeHostedAvatars: false,
        includeOwnedBuiltinActions: true,
      });
      if (!signal?.aborted && syncId === unifiedAvatarCatalogSyncId.current) {
        setSegmentedAvatarCatalog(catalog);
      }
    } catch {
      // Keep the last successful Avatar catalog when a backing service is unavailable.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refreshAssets = () => {
      setAssetCatalogHydrated(true);
      setAssetCatalogRevision((revision) => revision + 1);
      void loadSegmentedAssets();
      void loadUnifiedAvatarCatalog();
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refreshAssets();
    };
    setAssetCatalogHydrated(true);
    void loadSegmentedAssets(controller.signal);
    void loadUnifiedAvatarCatalog(controller.signal);
    window.addEventListener("focus", refreshAssets);
    window.addEventListener("storage", refreshAssets);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      controller.abort();
      segmentedCatalogSyncId.current += 1;
      unifiedAvatarCatalogSyncId.current += 1;
      window.removeEventListener("focus", refreshAssets);
      window.removeEventListener("storage", refreshAssets);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [loadSegmentedAssets, loadUnifiedAvatarCatalog]);

  const activeProvider = AVATAR_PROVIDER_OPTIONS.find((provider) => provider.id === avatarDisplayConfig.provider) ?? AVATAR_PROVIDER_OPTIONS[0];
  const currentHostedChoice = useMemo<HomeAvatarChoice>(() => ({
    id: hostedChoiceId(avatarDisplayConfig),
    name: avatarDisplayConfig.hostedAvatarDisplayName ?? "当前配置形象",
    role: `${activeProvider.name} · 当前配置`,
    preview: avatarDisplayConfig.hostedAvatarImageUrl,
    config: { ...avatarDisplayConfig, renderPath: "hosted" },
  }), [activeProvider.name, avatarDisplayConfig]);
  const providerHostedChoices = useMemo(() => avatarDisplayConfig.provider === "anam"
    ? hostedAvatars.map<HomeAvatarChoice>((avatar) => ({
        id: `hosted:anam:${avatar.id}`,
        name: avatar.displayName,
        role: avatar.origin === "personal" ? "自定义数字人" : "官方数字人",
        preview: avatar.imageUrl,
        providerAvatarId: avatar.origin === "personal" ? avatar.id : undefined,
        config: {
          ...avatarDisplayConfig,
          renderPath: "hosted",
          provider: "anam",
          avatarProfileId: avatar.id,
          hostedAvatarDisplayName: avatar.displayName,
          hostedAvatarImageUrl: avatar.imageUrl,
        },
      }))
    : [], [avatarDisplayConfig, hostedAvatars]);
  useEffect(() => {
    if (avatarDisplayConfig.provider !== "anam" || !hostedAvatars.length) return;
    const catalogId = avatarDisplayConfig.avatarProfileId === "default-anam"
      ? hostedDefaultAvatarId
      : avatarDisplayConfig.avatarProfileId;
    const catalogAvatar = hostedAvatars.find((avatar) => avatar.id === catalogId);
    if (!catalogAvatar) return;
    if (
      avatarDisplayConfig.hostedAvatarDisplayName === catalogAvatar.displayName
      && avatarDisplayConfig.hostedAvatarImageUrl === catalogAvatar.imageUrl
    ) return;
    onAvatarDisplayConfigChange({
      ...avatarDisplayConfig,
      hostedAvatarDisplayName: catalogAvatar.displayName,
      hostedAvatarImageUrl: catalogAvatar.imageUrl,
    });
  }, [avatarDisplayConfig, hostedAvatars, hostedDefaultAvatarId, onAvatarDisplayConfigChange]);
  const providerDefaultResolved = avatarDisplayConfig.provider === "anam"
    && Boolean(hostedDefaultAvatarId)
    && providerHostedChoices.some((choice) => choice.id === `hosted:anam:${hostedDefaultAvatarId}`);
  const hostedPersonalChoices = useMemo(() => {
    const personal = providerHostedChoices.filter((choice) => choice.role === "自定义数字人");
    if (!providerDefaultResolved && !personal.some((choice) => choice.id === currentHostedChoice.id)) {
      personal.unshift(currentHostedChoice);
    }
    return personal;
  }, [currentHostedChoice, providerDefaultResolved, providerHostedChoices]);
  const hostedOfficialChoices = useMemo(
    () => providerHostedChoices.filter((choice) => choice.role === "官方数字人"),
    [providerHostedChoices],
  );
  const segmentedAvatarCount = useMemo(
    () => filterSegmentedAvatarAssets(segmentedAvatarCatalog).length,
    [segmentedAvatarCatalog],
  );
  const segmentedAssetCatalog = useMemo(() => {
    void assetCatalogRevision;
    return readDigitalHumanAssetCatalog(savedMotionAssets, { includeLocal: assetCatalogHydrated });
  }, [assetCatalogHydrated, assetCatalogRevision, savedMotionAssets]);
  const segmentedMotionChoices = useMemo(
    () => buildSegmentedMotionChoices(avatarDisplayConfig, segmentedAssetCatalog),
    [avatarDisplayConfig, segmentedAssetCatalog],
  );
  const segmentedIdentityChoices = useMemo(
    () => buildSegmentedIdentityChoices(avatarDisplayConfig, segmentedAssetCatalog),
    [avatarDisplayConfig, segmentedAssetCatalog],
  );
  const selectedHostedId = avatarDisplayConfig.provider === "anam"
    && avatarDisplayConfig.avatarProfileId === "default-anam"
    && providerDefaultResolved
    ? `hosted:anam:${hostedDefaultAvatarId}`
    : hostedChoiceId(avatarDisplayConfig);
  const selectedMotionId = segmentedMotionChoiceId(avatarDisplayConfig);
  const selectedIdentityId = segmentedIdentityChoiceId(avatarDisplayConfig);
  const selectedSegmentedMotionChoice = segmentedMotionChoices.find((item) => item.id === selectedMotionId);
  const selectedSegmentedIdentityChoice = segmentedIdentityChoices.find((item) => item.id === selectedIdentityId);
  const selectedUnifiedAvatar = segmentedAvatarCatalog.find((avatar) => avatar.avatarId === avatarDisplayConfig.segmentedAvatarId);
  const selectedUnifiedAction = selectedUnifiedAvatar?.actions.find((action) => action.avatarActionId === avatarDisplayConfig.segmentedAvatarActionId);
  const selectedUnifiedChoice: HomeAvatarChoice | undefined = selectedUnifiedAvatar ? {
    id: selectedUnifiedAction ? `segmented-motion:${selectedUnifiedAction.avatarActionId}` : `segmented-identity:${selectedUnifiedAvatar.avatarId}`,
    name: selectedUnifiedAction?.displayName ?? selectedUnifiedAvatar.displayName,
    avatarName: selectedUnifiedAvatar.displayName,
    role: selectedUnifiedAction ? "配套动作" : "使用形象",
    preview: selectedUnifiedAvatar.source.imageUrl,
    motion: selectedUnifiedAction?.videoUrl ?? undefined,
    config: avatarDisplayConfig,
  } : undefined;
  const currentSegmentedChoice: HomeAvatarChoice = {
    id: `segmented-current:${avatarDisplayConfig.segmentedAvatarId}`,
    name: avatarDisplayConfig.segmentedDisplayName || avatarDisplayConfig.segmentedAvatarId,
    avatarName: avatarDisplayConfig.segmentedDisplayName || avatarDisplayConfig.segmentedAvatarId,
    role: "当前配置",
    preview: avatarDisplayConfig.segmentedAvatarId.startsWith("avatar-")
      ? `/api/avatars/${encodeURIComponent(avatarDisplayConfig.segmentedAvatarId)}/image`
      : undefined,
    config: avatarDisplayConfig,
  };
  const selectedAvatar = avatarDisplayConfig.renderPath === "hosted"
    ? [...hostedPersonalChoices, ...hostedOfficialChoices].find((item) => item.id === selectedHostedId) ?? currentHostedChoice
    : resolveSegmentedHomePreview(segmentedPreviewKind, {
      unified: selectedUnifiedChoice,
      motion: selectedSegmentedMotionChoice,
      identity: selectedSegmentedIdentityChoice,
      current: currentSegmentedChoice,
    });
  const selectedOrb = ORB_OPTIONS.find((item) => item.id === visualTheme) ?? ORB_OPTIONS[0];
  const orbOptions = [selectedOrb, ...ORB_OPTIONS.filter((item) => item.id !== selectedOrb.id)];
  const tabs: readonly { id: ConfigTab; label: string }[] = [
    { id: "appearance", label: "呈现" },
    { id: "voice", label: "音色" },
    { id: "model", label: "模型" },
    { id: "tools", label: "工具" },
    { id: "conversation", label: "对话" },
    { id: "general", label: "通用" },
  ];

  function selectMode(mode: ExperienceMode) {
    onExperienceModeChange(mode);
  }

  function selectTab(tab: ConfigTab) {
    setActiveTab(tab);
  }

  function openConfigTab(tab: ConfigTab) {
    setPanelState((current) => (current === "collapsed" ? "compact" : current));
    setActiveTab(tab);
  }

  function closePanelFromBlankPreview(event: ReactPointerEvent<HTMLDivElement>) {
    if (panelState === "collapsed") return;
    const target = event.target;
    if (!(target instanceof Element) || panelRef.current?.contains(target)) return;
    if (target.closest("button, a, input, textarea, select, [role=dialog], [role=menu], [role=alertdialog]")) return;
    setPanelState("collapsed");
  }

  function selectAvatarRenderPath(renderPath: AvatarDisplayConfig["renderPath"]) {
    const nextConfig = renderPath === "segmented"
      ? activateMacLipSyncRuntime(avatarDisplayConfig, MAC_LIP_SYNC_RUNTIME_CHOICES[0].id)
      : { ...avatarDisplayConfig, renderPath };
    onAvatarDisplayConfigChange(nextConfig);
    if (renderPath === "segmented") setSegmentedPreviewKind("motion");
  }

  function selectAvatarProvider(provider: AvatarProvider) {
    setOfficialAvatarsExpanded(false);
    onAvatarDisplayConfigChange({
      ...avatarDisplayConfig,
      renderPath: "hosted",
      provider,
      avatarProfileId: provider === "anam" ? "default-anam" : provider === "heygen" ? "default-heygen" : "default-custom",
      hostedAvatarDisplayName: undefined,
      hostedAvatarImageUrl: undefined,
    });
  }

  function selectSegmentedAvatarAsset(avatar: AvatarAsset, action: AvatarAction | null) {
    setSegmentedPreviewKind(action ? "motion" : "identity");
    onAvatarDisplayConfigChange({
      ...avatarDisplayConfig,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: avatar.avatarId,
      segmentedDisplayName: avatar.displayName,
      segmentedAvatarActionId: action?.avatarActionId
        ?? (avatar.ownerId ? `builtin:identity-static:${avatar.avatarId}` : ""),
    });
  }

  function updatePanelTransparency(value: number) {
    setPanelTransparency(value);
    writeWorkbenchVisualPreferences({ transparency: value, glassBlur: panelGlassBlur });
  }

  function updatePanelGlassBlur(value: number) {
    setPanelGlassBlur(value);
    writeWorkbenchVisualPreferences({ transparency: panelTransparency, glassBlur: value });
  }

  function openAvatarRename(item: HomeAvatarChoice) {
    if (!item.providerAvatarId) return;
    setRenameTarget(item);
    setRenameValue(item.name);
    setRenameError("");
  }

  function closeAvatarRename() {
    if (renamingAvatar) return;
    setRenameTarget(null);
    setRenameError("");
  }

  async function submitAvatarRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameTarget?.providerAvatarId || renamingAvatar) return;
    const displayName = renameValue.trim();
    if (!displayName || displayName.length > 50) {
      setRenameError("名称不能为空且不能超过 50 个字符");
      return;
    }
    setRenamingAvatar(true);
    setRenameError("");
    try {
      const response = await fetch("/api/anam/avatars", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatarId: renameTarget.providerAvatarId, displayName }),
      });
      const payload = await readAvatarMutationPayload(response);
      if (!response.ok || !payload.avatar) throw new Error(payload.error || "数字人名称修改失败");
      setHostedAvatars((current) => current.map((avatar) => (
        avatar.id === payload.avatar?.id ? payload.avatar : avatar
      )));
      if (avatarDisplayConfig.avatarProfileId === payload.avatar.id) {
        onAvatarDisplayConfigChange({
          ...avatarDisplayConfig,
          hostedAvatarDisplayName: payload.avatar.displayName,
          hostedAvatarImageUrl: payload.avatar.imageUrl,
        });
      }
      setRenameTarget(null);
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "数字人名称修改失败");
    } finally {
      setRenamingAvatar(false);
    }
  }

  const selectedAvatarName = selectedAvatar.avatarName ?? selectedAvatar.name;
  const workbenchPersonaAvatarId = avatarPersonaSelectionId({
    renderPath: avatarDisplayConfig.renderPath,
    avatarProfileId: avatarDisplayConfig.avatarProfileId,
    segmentedAvatarId: avatarDisplayConfig.segmentedAvatarId,
  });
  const startLabel = experienceMode === "voice"
    ? "使用对话模式开始对话"
    : `与 ${selectedAvatarName} 开始对话`;
  const selectedSegmentedRuntimeReady = avatarDisplayConfig.renderPath !== "segmented"
    || Boolean(getSegmentedAvatarRuntime(avatarDisplayConfig));
  const advancedTab: AdvancedConfigTab = activeTab === "appearance" ? "general" : activeTab;
  const panelTokens = workbenchSurfaceTokens({ transparency: panelTransparency, glassBlur: panelGlassBlur });
  const panelStyle = {
    "--panel-surface-alpha": panelTokens.surfaceAlpha,
    "--panel-highlight-alpha": panelTokens.highlightAlpha,
    "--panel-soft-alpha": panelTokens.softAlpha,
    "--panel-blur": panelTokens.blur,
  } as CSSProperties;

  function renderAvatarChoice(item: HomeAvatarChoice, selected: boolean, onSelect: () => void) {
    return (
      <span key={item.id} className={styles.avatarChoiceShell} data-manageable={Boolean(item.providerAvatarId)}>
        <button className={styles.avatarChoiceButton} type="button" data-active={selected} aria-pressed={selected} onClick={onSelect}>
          <span className={styles.avatarThumb}>
            {item.preview ? <Image src={item.preview} alt="" fill sizes="96px" /> : <UserRound aria-hidden="true" />}
            {item.motion ? <i>动作</i> : null}
          </span>
          <span><strong>{item.name}</strong><small>{item.role}{selected ? " · 当前使用" : ""}</small></span>
          {item.providerAvatarId ? null : selected ? <Check /> : <ChevronRight />}
        </button>
        {item.providerAvatarId ? (
          <button
            className={styles.avatarRenameButton}
            type="button"
            aria-label={`修改 ${item.name} 名称`}
            title="修改名称"
            onClick={() => openAvatarRename(item)}
          >
            <Pencil />
          </button>
        ) : null}
      </span>
    );
  }

  function renderHostedAvatarImageChoice(item: HomeAvatarChoice, selected: boolean, onSelect: () => void) {
    return (
      <button
        key={item.id}
        className={styles.hostedAvatarImageCard}
        type="button"
        data-active={selected}
        aria-label={`选择自定义数字人：${item.name}`}
        aria-pressed={selected}
        title={item.name}
        onClick={onSelect}
      >
        {item.preview ? (
          <>
            <Image
              className={styles.hostedAvatarBackdrop}
              src={item.preview}
              alt=""
              fill
              sizes="(max-width: 720px) 42vw, 150px"
              unoptimized={shouldLoadAvatarPreviewDirectly(item.preview)}
            />
            <Image
              className={styles.hostedAvatarPortrait}
              src={item.preview}
              alt=""
              fill
              sizes="(max-width: 720px) 42vw, 150px"
              unoptimized={shouldLoadAvatarPreviewDirectly(item.preview)}
            />
          </>
        ) : (
          <UserRound aria-hidden="true" />
        )}
        {selected ? <span className={styles.hostedAvatarSelectedMark}><Check aria-hidden="true" /></span> : null}
      </button>
    );
  }

  return (
    <div className={styles.workspace} data-mode={experienceMode === "voice" ? "orb" : "avatar"} data-orb-theme={visualTheme} data-reduced-motion={reducedMotion} style={panelStyle} onPointerDown={closePanelFromBlankPreview}>
      <div className={styles.preview} aria-live="polite">
        <div className={styles.atmosphere} aria-hidden="true"><i /><i /><i /></div>
        <div className={styles.orbPreview} data-visible={experienceMode === "voice"}>
          <div className={styles.orbHalo} aria-hidden="true" />
          {experienceMode === "voice" && <Orb state="listening" level={previewEnergy / 100} theme={visualTheme} />}
        </div>
        <div className={styles.avatarPreview} data-visible={experienceMode === "avatar"}>
          {selectedAvatar.motion && !reducedMotion ? (
            <MainAvatarMotionPreview key={selectedAvatar.id} choice={selectedAvatar} />
          ) : selectedAvatar.preview ? (
            <>
              <Image
                className={styles.avatarPreviewMotionBackdrop}
                src={selectedAvatar.preview}
                alt=""
                aria-hidden="true"
                fill
                sizes="100vw"
                unoptimized={shouldLoadAvatarPreviewDirectly(selectedAvatar.preview)}
              />
              <Image
                className={styles.avatarPreviewForeground}
                src={selectedAvatar.preview}
                alt={`${selectedAvatarName} 数字人预览`}
                fill
                priority
                sizes="100vw"
                unoptimized={shouldLoadAvatarPreviewDirectly(selectedAvatar.preview)}
              />
            </>
          ) : <div className={styles.avatarPreviewPlaceholder}><UserRound aria-hidden="true" /></div>}
          <div className={styles.avatarWash} aria-hidden="true" />
        </div>

        <div className={styles.previewCopy}>
          <span><i />LIVE PREVIEW</span>
          <h1>{experienceMode === "voice" ? selectedOrb.name : selectedAvatarName}</h1>
        </div>

      </div>

      <div className={styles.homeStartAction}>
        <VoiceStartButton
          connected={connected}
          disabled={experienceMode === "avatar" && !selectedSegmentedRuntimeReady}
          ariaLabel="主页开始对话"
          label={experienceMode === "voice" ? "开始语音对话" : `与 ${selectedAvatarName} 对话`}
          hint={experienceMode === "voice"
            ? ""
            : selectedSegmentedRuntimeReady
              ? ""
              : "请选择可用的数字人动作"}
          onPress={() => onStartSession(experienceMode)}
        />
      </div>

      <nav className={`${styles.modeSwitch} ${styles.homeModeDock}`} data-transparency={panelTransparency} data-glass-blur={panelGlassBlur} aria-label="主页呈现模式">
        <span className={styles.modeSwitchTrack} data-mode={experienceMode === "voice" ? "orb" : "avatar"} aria-hidden="true" />
        <button type="button" data-active={experienceMode === "voice"} aria-pressed={experienceMode === "voice"} onClick={() => selectMode("voice")}>
          <Sparkles />对话
        </button>
        <button type="button" data-active={experienceMode === "avatar"} aria-pressed={experienceMode === "avatar"} onClick={() => selectMode("avatar")}>
          <UserRound />数字人
        </button>
      </nav>

      <section ref={panelRef} className={styles.liquidPanel} data-state={panelState} data-transparency={panelTransparency} data-glass-blur={panelGlassBlur} aria-label="会话配置工作台">
        <div className={styles.glassShine} aria-hidden="true" />
        {panelState === "collapsed" ? (
          <button type="button" className={styles.collapsedSummary} aria-label="展开会话配置工作台" title="会话配置" onClick={() => setPanelState("compact")}>
            <span className={styles.summaryIcon}><SlidersHorizontal /></span>
          </button>
        ) : (
          <>
            <header className={styles.panelHeader}>
              <div className={styles.panelTitle}>
                <span><SlidersHorizontal /></span>
                <div><strong>会话配置工作台</strong></div>
              </div>
              <div className={styles.panelActions}>
                <Link className={styles.assetManagerLink} href="/avatars" aria-label="进入数字人资产管理">
                  <FolderOpen /><span>数字人资产管理</span>
                </Link>
                <button type="button" aria-label={panelState === "expanded" ? "缩小配置窗" : "展开配置窗"} onClick={() => setPanelState(panelState === "expanded" ? "compact" : "expanded")}>
                  {panelState === "expanded" ? <Minimize2 /> : <Maximize2 />}
                </button>
                <button type="button" aria-label="收起会话配置工作台" onClick={() => setPanelState("collapsed")}><ChevronDown /></button>
              </div>
            </header>

            <nav className={styles.configTabs} aria-label="配置分类">
              {tabs.map((tab) => {
                const Icon = TAB_ICONS[tab.id];
                return <button key={tab.id} type="button" data-active={activeTab === tab.id} aria-pressed={activeTab === tab.id} onClick={() => selectTab(tab.id)}><Icon /><span>{tab.label}</span></button>;
              })}
            </nav>

            <div className={styles.panelBody}>
              {activeTab === "appearance" ? (
                <div className={styles.appearanceModeHeader}>
                  <div className={styles.appearanceModeTitle}>
                    <strong>视觉呈现</strong>
                  </div>
                  <nav className={`${styles.modeSwitch} ${styles.workbenchModeSwitch}`} aria-label="视觉呈现模式">
                    <span className={styles.modeSwitchTrack} data-mode={experienceMode === "voice" ? "orb" : "avatar"} aria-hidden="true" />
                    <button type="button" data-active={experienceMode === "voice"} aria-pressed={experienceMode === "voice"} onClick={() => selectMode("voice")}>
                      <Sparkles />对话
                    </button>
                    <button type="button" data-active={experienceMode === "avatar"} aria-pressed={experienceMode === "avatar"} onClick={() => selectMode("avatar")}>
                      <UserRound />数字人
                    </button>
                  </nav>
                </div>
              ) : null}

              {activeTab === "appearance" && experienceMode === "voice" ? (
                <div className={styles.configView}>
                  <div className={styles.orbChoices}>
                    {orbOptions.map((item) => (
                      <button key={item.id} type="button" data-active={visualTheme === item.id} aria-pressed={visualTheme === item.id} onClick={() => onVisualThemeChange(item.id)}>
                        <VisualThemePreview theme={item.id} colors={item.colors} />
                        <span><strong>{item.name}</strong><small>{item.note}</small></span>
                        {visualTheme === item.id ? <Check /> : null}
                      </button>
                    ))}
                  </div>
                  <label className={styles.rangeControl}><span><span><Sparkles />预览动效</span><b>{previewEnergy}%</b></span><input type="range" min="10" max="90" value={previewEnergy} onChange={(event) => setPreviewEnergy(Number(event.target.value))} /></label>
                </div>
              ) : null}

              {activeTab === "appearance" && experienceMode === "avatar" ? (
                <div className={`${styles.configView} ${styles.avatarConfigView}`}>
                  <div className={styles.avatarRenderPathSwitch} role="group" aria-label="数字人驱动方式">
                    <button type="button" data-active={avatarDisplayConfig.renderPath === "hosted"} aria-pressed={avatarDisplayConfig.renderPath === "hosted"} onClick={() => selectAvatarRenderPath("hosted")}>
                      <span><UserRound /></span><span><strong>实时驱动</strong><small>供应商实时生成动作与口型</small></span>{avatarDisplayConfig.renderPath === "hosted" ? <Check /> : null}
                    </button>
                    <button type="button" data-active={avatarDisplayConfig.renderPath === "segmented"} aria-pressed={avatarDisplayConfig.renderPath === "segmented"} onClick={() => selectAvatarRenderPath("segmented")}>
                      <span><Film /></span><span><strong>多段式合成</strong><small>动作资产与形象资产组合</small></span>{avatarDisplayConfig.renderPath === "segmented" ? <Check /> : null}
                    </button>
                  </div>

                  {avatarDisplayConfig.renderPath === "hosted" ? (
                    <>
                      <section className={styles.avatarProviderSection}>
                        <header>
                          <span><strong>实时驱动供应商</strong></span>
                          <Link className={styles.avatarProviderCreateButton} href="/avatars/create"><Plus />创建数字人</Link>
                        </header>
                        <div className={styles.avatarProviderChoices}>
                          {AVATAR_PROVIDER_OPTIONS.map((provider) => (
                            <button key={provider.id} type="button" data-active={avatarDisplayConfig.provider === provider.id} aria-pressed={avatarDisplayConfig.provider === provider.id} onClick={() => selectAvatarProvider(provider.id)}>
                              <span><strong>{provider.name}</strong><small>{provider.note}</small></span><em>{provider.status}</em>{avatarDisplayConfig.provider === provider.id ? <Check /> : null}
                            </button>
                          ))}
                        </div>
                      </section>

                      <div className={styles.avatarAssetColumns}>
                        <section className={styles.avatarAssetGroup}>
                          <header>
                            <span><strong>自定义数字人</strong><small>{activeProvider.name} 个人形象</small></span>
                            <span className={styles.avatarAssetHeaderActions}>
                              <em>{hostedPersonalChoices.length}</em>
                              {avatarDisplayConfig.provider === "anam" ? (
                                <button
                                  type="button"
                                  className={styles.avatarCatalogSyncButton}
                                  aria-label="同步 Anam 数字人名称"
                                  title="同步 Anam 数字人"
                                  disabled={hostedCatalogSyncing}
                                  onClick={() => void loadHostedAvatars()}
                                >
                                  <RefreshCw data-spinning={hostedCatalogSyncing} />
                                </button>
                              ) : null}
                            </span>
                          </header>
                          <div className={`${styles.hostedAvatarImageGrid} ${styles.avatarAssetScroll}`} aria-label={`${activeProvider.name} 自定义数字人列表`}>
                            {hostedPersonalChoices.map((item) => renderHostedAvatarImageChoice(item, selectedHostedId === item.id, () => onAvatarDisplayConfigChange(item.config)))}
                          </div>
                        </section>
                        <section className={styles.avatarAssetGroup}>
                          <header>
                            <span><strong>官方数字人</strong><small>{activeProvider.name} 官方目录</small></span>
                            <span className={styles.avatarAssetHeaderActions}>
                              <em>{hostedOfficialChoices.length}</em>
                              <button
                                type="button"
                                className={styles.officialAvatarToggle}
                                aria-label={officialAvatarsExpanded ? "收起官方数字人" : "展开官方数字人"}
                                aria-expanded={officialAvatarsExpanded}
                                onClick={() => setOfficialAvatarsExpanded((expanded) => !expanded)}
                              >
                                <ChevronDown aria-hidden="true" />
                              </button>
                            </span>
                          </header>
                          {officialAvatarsExpanded && hostedOfficialChoices.length ? (
                            <div className={`${styles.avatarChoices} ${styles.avatarAssetScroll}`} aria-label={`${activeProvider.name} 官方数字人列表`}>
                              {hostedOfficialChoices.map((item) => renderAvatarChoice(item, selectedHostedId === item.id, () => onAvatarDisplayConfigChange(item.config)))}
                            </div>
                          ) : officialAvatarsExpanded ? (
                            <p className={styles.avatarAssetEmpty}>{avatarDisplayConfig.provider === "anam" ? "当前目录没有可用的官方数字人" : `${activeProvider.name} 目录尚未接入，配置服务凭据后同步`}</p>
                          ) : null}
                        </section>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className={styles.segmentedAvatarAssets}>
                        <div className={styles.segmentedAvatarAssetsHeader}>
                          <span><strong>Avatar 资产（{segmentedAvatarCount}）</strong></span>
                          <Link href="/avatars/create?task=action"><Plus />创建 Avatar 动作</Link>
                        </div>
                        <SegmentedAvatarAssetPicker
                          avatars={segmentedAvatarCatalog}
                          selectedAvatarId={avatarDisplayConfig.segmentedAvatarId}
                          selectedActionId={avatarDisplayConfig.segmentedAvatarActionId}
                          disabled={false}
                          active={!reducedMotion}
                          showCollapsedSummary={false}
                          onSelect={selectSegmentedAvatarAsset}
                        />
                      </div>
                      <section className={styles.macLipSyncSection} aria-labelledby="mac-lip-sync-title">
                        <header>
                          <h3 id="mac-lip-sync-title">口型模型</h3>
                          <select
                            className={styles.macLipSyncChoices}
                            aria-label="口型模型选择"
                            value={MAC_LIP_SYNC_RUNTIME_CHOICES.some(
                              (model) => model.id === avatarDisplayConfig.segmentedLipSyncId,
                            ) ? avatarDisplayConfig.segmentedLipSyncId : MAC_LIP_SYNC_RUNTIME_CHOICES[0].id}
                            onChange={(event) => {
                              const model = MAC_LIP_SYNC_RUNTIME_CHOICES.find(
                                (candidate) => candidate.id === event.currentTarget.value,
                              );
                              if (!model) return;
                              setSegmentedPreviewKind("motion");
                              onAvatarDisplayConfigChange(activateMacLipSyncRuntime(avatarDisplayConfig, model.id));
                            }}
                          >
                            {MAC_LIP_SYNC_RUNTIME_CHOICES.map((model, index) => (
                              <option key={model.id} value={model.id}>
                                {model.name}{index === 0 ? "（默认）" : ""}
                              </option>
                            ))}
                          </select>
                        </header>
                      </section>
                    </>
                  )}
                </div>
              ) : null}

              {activeTab !== "appearance" ? (
                <div className={styles.advancedSettingsBody} data-direct="true">
                  {activeTab === "general" ? (
                    <div className={styles.workspaceVisualControls}>
                      <label className={`${styles.rangeControl} ${styles.workspaceVisualControl}`}>
                        <span><span><SlidersHorizontal />工作台透明度<InfoHint text="提高后可看到更多主页预览，文字与控件保持清晰。" /></span><b>{panelTransparency}%</b></span>
                        <input
                          type="range"
                          min="12"
                          max="88"
                          value={panelTransparency}
                          aria-label="工作台透明度"
                          onChange={(event) => updatePanelTransparency(Number(event.target.value))}
                        />
                      </label>
                      <label className={`${styles.rangeControl} ${styles.workspaceVisualControl}`}>
                        <span><span><Gauge />毛玻璃模糊<InfoHint text="降低后可保留更多背景动效细节，提高后文字衬底更稳定。" /></span><b>{panelGlassBlur}%</b></span>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={panelGlassBlur}
                          aria-label="毛玻璃模糊"
                          onChange={(event) => updatePanelGlassBlur(Number(event.target.value))}
                        />
                      </label>
                    </div>
                  ) : null}
                  {renderAdvancedSettings(advancedTab, setSelectedVoiceLabel, IGNORE_MODEL_LABEL_CHANGE)}
                </div>
              ) : null}
            </div>

            <footer className={styles.panelFooter}>
              <div className={styles.selectionSummary}>
                <button type="button" className={styles.selectionChip} onClick={() => openConfigTab("appearance")}>
                  <span className={styles.selectionChipIcon}>{modeIcon(experienceMode)}</span>
                  <span className={styles.selectionChipText}>
                    <small>{experienceMode === "voice" ? "对话形象" : "数字人"}</small>
                    <strong>{experienceMode === "voice" ? selectedOrb.name : selectedAvatarName}</strong>
                  </span>
                </button>
                <button type="button" className={styles.selectionChip} onClick={() => openConfigTab("voice")}>
                  <span className={styles.selectionChipIcon}><Volume2 /></span>
                  <span className={styles.selectionChipText}>
                    <small>音色</small>
                    <strong>{selectedVoiceLabel}</strong>
                  </span>
                </button>
                <PersonaQuickSelect avatarId={workbenchPersonaAvatarId} avatarDisplayName={selectedAvatarName} />
              </div>
              <button type="button" className={styles.startButton} disabled={!connected} onClick={() => onStartSession(experienceMode)}>
                <span><Play /></span>{connected ? startLabel : "语音服务准备中"}<ChevronRight />
              </button>
            </footer>
          </>
        )}
      </section>

      {renameTarget ? (
        <div className={styles.avatarRenameBackdrop} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && closeAvatarRename()}>
          <section className={styles.avatarRenameDialog} role="dialog" aria-modal="true" aria-labelledby="avatar-rename-title">
            <button type="button" className={styles.avatarRenameClose} aria-label="关闭" disabled={renamingAvatar} onClick={closeAvatarRename}><X /></button>
            <span className={styles.avatarRenameIcon}><Pencil /></span>
            <div className={styles.avatarRenameCopy}>
              <small>ANAM CUSTOM AVATAR</small>
              <h2 id="avatar-rename-title">修改数字人名称</h2>
              <p>新名称会同步到 Anam，并用于当前工作台和后续选择。</p>
            </div>
            <form onSubmit={submitAvatarRename}>
              <label>
                <span>名称</span>
                <input autoFocus value={renameValue} maxLength={50} disabled={renamingAvatar} onChange={(event) => setRenameValue(event.target.value)} />
              </label>
              {renameError ? <p role="alert">{renameError}</p> : null}
              <div>
                <button type="button" disabled={renamingAvatar} onClick={closeAvatarRename}>取消</button>
                <button type="submit" disabled={renamingAvatar || renameValue.trim() === renameTarget.name}>{renamingAvatar ? "正在保存…" : "保存名称"}</button>
              </div>
            </form>
          </section>
        </div>
      ) : null}

      {error ? <p className={styles.homeError} role="alert">{error}</p> : null}
    </div>
  );
}
