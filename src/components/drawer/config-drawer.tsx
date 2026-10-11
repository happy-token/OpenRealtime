"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  AudioLines,
  BrainCircuit,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Copy,
  FileText,
  Film,
  Globe2,
  MessageCircle,
  Mic2,
  Monitor,
  Pause,
  Play,
  Plus,
  Radio,
  Settings2,
  Sparkles,
  Square,
  Trash2,
  UserRound,
  Video,
  Wrench,
  X,
} from "lucide-react";
import { DEFAULT_ALLOW_BARGE_IN } from "@/hooks/use-voice-session";
import { readConversationPreferences, writeConversationPreferences } from "@/lib/conversation-preferences";
import type { VoiceVisualTheme } from "@/components/call/voice-theme";
import type { AvatarDisplayConfig, ExperienceMode } from "@/components/digital-human/types";
import { HostedAvatarCatalog } from "@/components/digital-human/hosted-avatar-catalog";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import { getBuiltinAvatarAction } from "@/lib/builtin-avatar-actions";
import { INTERNAL_AVATAR_PRESET_IDS } from "@/lib/internal-avatar-ids";
import { readJsonResponse } from "@/lib/http-json-response";
import type { TtsConfigFrame } from "@/lib/frames";
import { getBuiltinMotionPreviewUrl } from "@/lib/builtin-motion-catalog";
import {
  EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES,
  hideAvatarLibraryAsset,
  persistAvatarAssetLibraryPreferences,
  readAvatarAssetLibraryPreferences,
  resolveAvatarDisplayConfigAfterDeletion,
} from "@/lib/avatar-asset-library-preferences";
import {
  fetchAvatarActionCatalog,
  avatarActionLabel,
  selectAvatarActionRendition,
  type AvatarActionAsset,
} from "@/lib/avatar-motion-catalog";
import {
  OPENTALKING_AVATAR_CATALOG,
  type OpenTalkingAvatarAsset,
} from "@/lib/opentalking-avatar-catalog";
import { BottomVoiceStylePicker } from "@/components/call/bottom-voice-style-picker";
import { ExperienceModeSwitch } from "@/components/call/experience-mode-switch";
import { ExperienceModeDemo } from "@/components/call/experience-mode-demo";
import { SelectMenu } from "@/components/ui/select-menu";
import { InfoHint } from "@/components/ui/info-hint";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  BAILIAN_DIALECT_OPTIONS,
  BAILIAN_TTS_VOICE_OPTIONS,
  DIALECT_TTS_VOICE,
  findTtsVoice,
  TTS_DIALECT_OPTIONS,
  TTS_PROVIDER_OPTIONS,
  TTS_VOICE_OPTIONS,
  type TtsDialect,
  type TtsProvider,
  type TtsVoice,
} from "@/components/drawer/voice-options";
import {
  findModelProvider,
  MODEL_PROTOCOL_OPTIONS,
  MODEL_PROVIDER_OPTIONS,
  type ModelProtocol,
  type ModelProvider,
} from "@/components/drawer/model-options";
import { VIDEO_BASE_CHOICES } from "@/components/digital-human/segmented-avatar-config";
import { VoiceClonePanel } from "@/components/drawer/voice-clone-panel";
import { SegmentedAvatarAssetPicker } from "@/components/drawer/segmented-avatar-asset-picker";
import type { AvatarAction, AvatarAsset } from "@/lib/avatar-catalog";
import {
  PERSONA_CREATE_OPTION_VALUE,
  avatarPersonaSelectionId,
  personaSelectOptions,
} from "@/lib/avatar-persona";
import { usePersonaLink } from "@/hooks/use-persona-link";
import { loadCurrentAvatarCatalog } from "@/lib/avatar-library-catalog-client";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  WORKBENCH_VISUAL_PREFERENCES_EVENT,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";
import {
  APP_THEME_OPTIONS,
  DEFAULT_APP_THEME,
  type AppTheme,
} from "@/lib/app-theme";

const COPY_FEEDBACK_MS = 1500;
const DEFAULT_VOLUME_PERCENT = 80;
const PERSONA_DRAFT_STORAGE_KEY = "openrealtime-persona-config-draft";
const CONFIG_TABS = [
  { id: "display", label: "呈现", icon: Monitor },
  { id: "model", label: "模型", icon: BrainCircuit },
  { id: "voice", label: "音色", icon: AudioLines },
  { id: "tools", label: "工具", icon: Wrench },
  { id: "conversation", label: "对话", icon: MessageCircle },
  { id: "general", label: "通用", icon: Settings2 },
] as const;

export type ConfigTab = (typeof CONFIG_TABS)[number]["id"];
const CONFIG_TAB_IDS = new Set<string>(CONFIG_TABS.map((tab) => tab.id));
export function isConfigTab(value: string): value is ConfigTab {
  return CONFIG_TAB_IDS.has(value);
}
export type TtsRuntimeConfig = {
  provider: TtsConfigFrame["provider"];
  voice: string;
  speechRate: number;
  dialect: TtsConfigFrame["dialect"];
};
type CustomToolDraft = { id: string; name: string; endpoint: string };
type PendingAvatarAssetDeletion = { kind: "identity" | "motion"; id: string; label: string };
const VISUAL_THEME_OPTIONS = [
  { value: "cloud", label: "云雾", description: "柔和粒子云" },
  { value: "liquid-glass", label: "液态玻璃", description: "LerSent WebGPU 流体玻璃" },
  { value: "aurora-particles", label: "极光粒子", description: "metasidd 辉光与粒子" },
  { value: "radial", label: "径向光盘", description: "环形频谱" },
  { value: "circle", label: "柔和圆形", description: "呼吸光晕" },
  { value: "bars", label: "音频柱", description: "实时柱状频谱" },
  { value: "debug", label: "调试面板", description: "状态与音量数据" },
] as const;
export const AVATAR_RENDER_PATH_OPTIONS = [
  { value: "hosted", label: "实时托管", description: "使用一张形象，由托管服务实时生成自然动作与口型" },
  { value: "segmented", label: "分段式合成", description: "使用预制动作视频，在会话中完成口型对齐" },
] as const;
const MOTION_ASSET_LABELS: Record<string, string> = {
  "avatar-bundled": "内置循环动作",
  "ffmpeg-static": "静态画面对照",
  "liveportrait-optimized": "自然交互动作",
};
const OPENTALKING_MOTION_ASSETS = OPENTALKING_AVATAR_CATALOG.filter(
  (asset): asset is OpenTalkingAvatarAsset & { motionVideoUrl: string } => Boolean(
    asset.motionVideoUrl && INTERNAL_AVATAR_PRESET_IDS.some(id => id === asset.id),
  ),
);
const MODEL_PROVIDER_MENU_OPTIONS = MODEL_PROVIDER_OPTIONS.map(({ value, label }) => ({ value, label }));
interface ConfigDrawerProps {
  open: boolean;
  initialTab?: ConfigTab;
  variant?: "drawer" | "embedded" | "session";
  onClose: () => void;
  setBargeInMuted: (muted: boolean) => void;
  setNoiseSuppression: (enabled: boolean) => void;
  setVolume: (volume: number) => void;
  sessionId: string | null;
  voiceVisualTheme: VoiceVisualTheme;
  onVoiceVisualThemeChange: (theme: VoiceVisualTheme) => void;
  ttsVoice: TtsVoice;
  initialTtsProvider?: TtsProvider;
  useRoleTtsConfig?: boolean;
  ttsSpeechRate: number;
  ttsDialect: TtsDialect;
  ttsConfigurable: boolean;
  ttsPreviewAvailable: boolean;
  publicVoiceEnabled?: boolean;
  ttsConfigStatus: string;
  onTtsVoiceChange: (voice: TtsVoice) => void;
  onTtsRuntimeConfigChange?: (config: TtsRuntimeConfig) => void;
  onSelectedVoiceLabelChange?: (label: string) => void;
  onSelectedModelLabelChange?: (label: string) => void;
  onTtsSpeechRateChange: (rate: number) => void;
  onTtsDialectChange: (dialect: TtsDialect) => void;
  experienceMode: ExperienceMode;
  onExperienceModeChange: (mode: ExperienceMode) => void;
  avatarDisplayConfig: AvatarDisplayConfig;
  onAvatarDisplayConfigChange: (config: AvatarDisplayConfig) => void;
  avatarConfigLocked: boolean;
  avatarArtifactPreviewEnabled: boolean;
  reducedMotion: boolean;
  onReducedMotionChange: (reduced: boolean) => void;
  appTheme?: AppTheme;
  onAppThemeChange?: (theme: AppTheme) => void;
}

export function ConfigDrawer({
  open,
  initialTab = "display",
  variant = "drawer",
  onClose,
  setBargeInMuted,
  setNoiseSuppression,
  setVolume,
  sessionId,
  voiceVisualTheme,
  onVoiceVisualThemeChange,
  ttsVoice,
  initialTtsProvider,
  useRoleTtsConfig = false,
  ttsSpeechRate,
  ttsDialect,
  ttsConfigurable,
  ttsPreviewAvailable,
  publicVoiceEnabled = false,
  ttsConfigStatus,
  onTtsVoiceChange,
  onTtsRuntimeConfigChange,
  onSelectedVoiceLabelChange,
  onSelectedModelLabelChange,
  onTtsSpeechRateChange,
  onTtsDialectChange,
  experienceMode,
  onExperienceModeChange,
  avatarDisplayConfig,
  onAvatarDisplayConfigChange,
  avatarConfigLocked,
  avatarArtifactPreviewEnabled,
  reducedMotion,
  onReducedMotionChange,
  appTheme = DEFAULT_APP_THEME,
  onAppThemeChange = () => undefined,
}: ConfigDrawerProps) {
  const { t } = useLanguage();
  const embedded = variant === "embedded";
  const sessionWorkbench = variant === "session";
  const defaultModelProvider = findModelProvider("deepseek");
  const [activeTab, setActiveTab] = useState<ConfigTab>(initialTab);
  const [copied, setCopied] = useState(false);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "playing">("idle");
  const [previewVoice, setPreviewVoice] = useState<TtsVoice | null>(null);
  const [previewNotice, setPreviewNotice] = useState("");
  const [playbackVolume, setPlaybackVolume] = useState(DEFAULT_VOLUME_PERCENT);
  const [allowBargeIn, setAllowBargeIn] = useState(DEFAULT_ALLOW_BARGE_IN);
  const [noiseSuppressionEnabled, setNoiseSuppressionEnabled] = useState(true);
  const [ttsProvider, setTtsProvider] = useState<TtsProvider>(() => initialTtsProvider ?? (ttsConfigurable ? "doubao" : "bailian"));
  const [bailianVoice, setBailianVoice] = useState<string>(() => useRoleTtsConfig ? ttsVoice : BAILIAN_CLONED_VOICE_OPTIONS[0].value);
  const [bailianVoiceLabel, setBailianVoiceLabel] = useState<string>(() => useRoleTtsConfig
    ? BAILIAN_TTS_VOICE_OPTIONS.find((voice) => voice.value === ttsVoice)?.label ?? ttsVoice
    : BAILIAN_CLONED_VOICE_OPTIONS[0].label);
  const [bailianDialect, setBailianDialect] = useState<string>(() => useRoleTtsConfig ? ttsDialect : "");
  const [modelProvider, setModelProvider] = useState<ModelProvider>(defaultModelProvider.value);
  const [modelId, setModelId] = useState(defaultModelProvider.models[0].value);
  const [modelProtocol, setModelProtocol] = useState<ModelProtocol>(defaultModelProvider.protocol);
  const [modelBaseUrl, setModelBaseUrl] = useState(defaultModelProvider.baseUrl);
  const [modelApiKeyEnv, setModelApiKeyEnv] = useState(defaultModelProvider.apiKeyEnv);
  const [modelWorkspaceId, setModelWorkspaceId] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("你是 Shuchang，一位温暖、直接、善于推进任务的产品协作伙伴。回答保持自然简洁，并在调用工具前说明意图。");
  const [customTools, setCustomTools] = useState<CustomToolDraft[]>([]);
  const [toolName, setToolName] = useState("");
  const [toolEndpoint, setToolEndpoint] = useState("");
  const [workbenchVisualPreferences, setWorkbenchVisualPreferences] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  const [classicMotionIntensity, setClassicMotionIntensity] = useState(68);
  const [selectedHostedAvatar, setSelectedHostedAvatar] = useState<Pick<AnamHostedAvatar, "id" | "displayName" | "imageUrl"> | null>(() => (
    avatarDisplayConfig.hostedAvatarImageUrl
      ? {
          id: avatarDisplayConfig.avatarProfileId,
          displayName: avatarDisplayConfig.hostedAvatarDisplayName ?? "当前配置形象",
          imageUrl: avatarDisplayConfig.hostedAvatarImageUrl,
        }
      : avatarDisplayConfig.avatarProfileId === "default-anam"
        ? { id: "default-anam", displayName: "当前环境形象", imageUrl: "" }
        : null
  ));
  const [motionBaseCatalog, setAvatarActionCatalog] = useState<AvatarActionAsset[]>([]);
  const [segmentedAvatarCatalog, setSegmentedAvatarCatalog] = useState<AvatarAsset[]>([]);
  const [motionBaseCatalogState, setAvatarActionCatalogState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [motionBaseCatalogNotice, setAvatarActionCatalogNotice] = useState("");
  const [assetLibraryPreferences, setAssetLibraryPreferences] = useState(EMPTY_AVATAR_ASSET_LIBRARY_PREFERENCES);
  const [pendingAvatarAssetDeletion, setPendingAvatarAssetDeletion] = useState<PendingAvatarAssetDeletion | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewUrlRef = useRef("");
  const previewRequestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) setActiveTab(initialTab);
  }, [initialTab, open]);

  useEffect(() => {
    if (!sessionWorkbench) return;
    const syncVisualPreferences = () => setWorkbenchVisualPreferences(readWorkbenchVisualPreferences());
    syncVisualPreferences();
    window.addEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, syncVisualPreferences);
    window.addEventListener("storage", syncVisualPreferences);
    return () => {
      window.removeEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, syncVisualPreferences);
      window.removeEventListener("storage", syncVisualPreferences);
    };
  }, [sessionWorkbench]);

  useEffect(() => {
    const preferences = readConversationPreferences();
    setPlaybackVolume(preferences.volume);
    setAllowBargeIn(preferences.allowBargeIn);
    setNoiseSuppressionEnabled(preferences.noiseSuppression);
    setVolume(preferences.volume / 100);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- set the initial volume once
  }, []);

  useEffect(() => {
    setAssetLibraryPreferences(readAvatarAssetLibraryPreferences());
  }, []);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(PERSONA_DRAFT_STORAGE_KEY) ?? "null") as {
        systemPrompt?: unknown;
        customTools?: unknown;
        ttsProvider?: unknown;
        bailianVoice?: unknown;
        bailianVoiceLabel?: unknown;
        bailianDialect?: unknown;
        modelProvider?: unknown;
        modelId?: unknown;
        modelProtocol?: unknown;
        modelBaseUrl?: unknown;
        modelApiKeyEnv?: unknown;
        modelWorkspaceId?: unknown;
        display?: unknown;
      } | null;
      if (!saved) return;
      if (typeof saved.systemPrompt === "string") setSystemPrompt(saved.systemPrompt);
      if (Array.isArray(saved.customTools)) {
        setCustomTools(saved.customTools.filter((tool): tool is CustomToolDraft => Boolean(
          tool && typeof tool === "object"
          && typeof (tool as CustomToolDraft).id === "string"
          && typeof (tool as CustomToolDraft).name === "string"
          && typeof (tool as CustomToolDraft).endpoint === "string",
        )));
      }
      if (!useRoleTtsConfig && (saved.ttsProvider === "bailian" || saved.ttsProvider === "doubao")) setTtsProvider(saved.ttsProvider);
      if (!useRoleTtsConfig && typeof saved.bailianVoice === "string") setBailianVoice(saved.bailianVoice);
      if (!useRoleTtsConfig && typeof saved.bailianVoiceLabel === "string") {
        const savedLabel = saved.bailianVoiceLabel.trim();
        setBailianVoiceLabel(
          savedLabel.toLocaleLowerCase() === "shuchang 克隆音色".toLocaleLowerCase()
            ? BAILIAN_CLONED_VOICE_OPTIONS[0].label
            : savedLabel,
        );
      }
      if (!useRoleTtsConfig && typeof saved.bailianDialect === "string") setBailianDialect(saved.bailianDialect);
      if (MODEL_PROVIDER_OPTIONS.some((provider) => provider.value === saved.modelProvider)) setModelProvider(saved.modelProvider as ModelProvider);
      if (typeof saved.modelId === "string") setModelId(saved.modelId);
      if (MODEL_PROTOCOL_OPTIONS.some((protocol) => protocol.value === saved.modelProtocol)) setModelProtocol(saved.modelProtocol as ModelProtocol);
      if (typeof saved.modelBaseUrl === "string") setModelBaseUrl(saved.modelBaseUrl);
      if (typeof saved.modelApiKeyEnv === "string") setModelApiKeyEnv(saved.modelApiKeyEnv);
      if (typeof saved.modelWorkspaceId === "string") setModelWorkspaceId(saved.modelWorkspaceId);
      if (saved.display && typeof saved.display === "object") {
        const display = saved.display as Record<string, unknown>;
        if (typeof display.reducedMotion === "boolean") onReducedMotionChange(display.reducedMotion);
        if (typeof display.classicMotionIntensity === "number") setClassicMotionIntensity(display.classicMotionIntensity);
      }
    } catch {
      window.localStorage.removeItem(PERSONA_DRAFT_STORAGE_KEY);
    }
  }, [onReducedMotionChange, useRoleTtsConfig]);

  const refreshAvatarActionCatalog = useCallback(async (signal?: AbortSignal) => {
    const visiblePackagedMotionCount = OPENTALKING_MOTION_ASSETS.filter((asset) => (
      !assetLibraryPreferences.hiddenMotionIds.includes(`opentalking:${asset.id}`)
    )).length;
    setAvatarActionCatalogState("loading");
    setAvatarActionCatalogNotice(`已载入 ${visiblePackagedMotionCount} 个本地动作 · 正在读取已保存动作`);
    try {
      const catalog = await fetchAvatarActionCatalog(undefined, fetch, signal);
      setAvatarActionCatalog(catalog.avatarActions);
      setAvatarActionCatalogState("ready");
      const visibleSavedMotionCount = catalog.avatarActions.filter((asset) => (
        !assetLibraryPreferences.hiddenMotionIds.includes(asset.avatar_action_id)
      )).length;
      setAvatarActionCatalogNotice(`${visiblePackagedMotionCount} 个本地动作 · ${visibleSavedMotionCount} 个已保存动作`);
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setAvatarActionCatalog([]);
      setAvatarActionCatalogState("error");
      setAvatarActionCatalogNotice(`已载入 ${visiblePackagedMotionCount} 个本地动作 · 已保存动作暂不可用`);
    }
  }, [assetLibraryPreferences.hiddenMotionIds]);

  useEffect(() => {
    if (!open || experienceMode !== "avatar" || avatarDisplayConfig.renderPath !== "segmented") return;
    const controller = new AbortController();
    void refreshAvatarActionCatalog(controller.signal);
    void loadCurrentAvatarCatalog(controller.signal, {
      includeHostedAvatars: false,
      includeOwnedBuiltinActions: true,
    }).then(setSegmentedAvatarCatalog).catch(() => undefined);
    return () => controller.abort();
  }, [avatarDisplayConfig.renderPath, experienceMode, open, refreshAvatarActionCatalog]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      window.localStorage.setItem(PERSONA_DRAFT_STORAGE_KEY, JSON.stringify({
        systemPrompt,
        customTools,
        ttsProvider,
        bailianVoice,
        bailianVoiceLabel,
        bailianDialect,
        modelProvider,
        modelId,
        modelProtocol,
        modelBaseUrl,
        modelApiKeyEnv,
        modelWorkspaceId,
        display: {
          reducedMotion,
          classicMotionIntensity,
        },
      }));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [bailianDialect, bailianVoice, bailianVoiceLabel, classicMotionIntensity, customTools, modelApiKeyEnv, modelBaseUrl, modelId, modelProtocol, modelProvider, modelWorkspaceId, reducedMotion, systemPrompt, ttsProvider]);

  useEffect(() => {
    if (previewAudioRef.current) previewAudioRef.current.volume = playbackVolume / 100;
  }, [playbackVolume]);

  const selectedModelProvider = findModelProvider(modelProvider);
  const selectedModelLabel = selectedModelProvider.models.find((model) => model.value === modelId)?.label ?? modelId;

  useEffect(() => {
    const label = ttsProvider === "bailian"
      ? bailianVoiceLabel
      : findTtsVoice(ttsVoice)?.label ?? "当前音色";
    onSelectedVoiceLabelChange?.(label);
  }, [bailianVoiceLabel, onSelectedVoiceLabelChange, ttsProvider, ttsVoice]);

  useEffect(() => {
    onTtsRuntimeConfigChange?.({
      provider: ttsProvider,
      voice: ttsProvider === "bailian" ? bailianVoice : ttsVoice,
      speechRate: ttsSpeechRate,
      dialect: (ttsProvider === "bailian" ? bailianDialect : ttsDialect) as TtsConfigFrame["dialect"],
    });
  }, [bailianDialect, bailianVoice, onTtsRuntimeConfigChange, ttsDialect, ttsProvider, ttsSpeechRate, ttsVoice]);

  useEffect(() => {
    onSelectedModelLabelChange?.(selectedModelLabel);
  }, [onSelectedModelLabelChange, selectedModelLabel]);

  useEffect(() => {
    if (!open || embedded) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (pendingAvatarAssetDeletion) setPendingAvatarAssetDeletion(null);
      else onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [embedded, open, onClose, pendingAvatarAssetDeletion]);

  useEffect(() => () => {
    previewRequestRef.current?.abort();
    previewAudioRef.current?.pause();
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  useEffect(() => {
    previewRequestRef.current?.abort();
    previewRequestRef.current = null;
    previewAudioRef.current?.pause();
    previewAudioRef.current = null;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = "";
    setPreviewState("idle");
    setPreviewVoice(null);
    setPreviewNotice("");
  }, [bailianDialect, bailianVoice, ttsDialect, ttsProvider, ttsSpeechRate, ttsVoice]);

  async function copySessionId() {
    if (!sessionId) return;
    try {
      await navigator.clipboard.writeText(sessionId);
    } catch {
      return;
    }
    setCopied(true);
    setTimeout(() => setCopied(false), COPY_FEEDBACK_MS);
  }

  function selectModelProvider(provider: ModelProvider) {
    const option = findModelProvider(provider);
    setModelProvider(option.value);
    setModelId(option.models[0].value);
    setModelProtocol(option.protocol);
    setModelBaseUrl(option.baseUrl);
    setModelApiKeyEnv(option.apiKeyEnv);
  }

  function selectBailianVoice(voiceId: string, label: string) {
    setBailianVoice(voiceId);
    setBailianVoiceLabel(label);
  }

  function selectHostedAvatar(avatar: Pick<AnamHostedAvatar, "id" | "displayName" | "imageUrl">) {
    setSelectedHostedAvatar(avatar);
    onAvatarDisplayConfigChange({
      ...avatarDisplayConfig,
      provider: "anam",
      avatarProfileId: avatar.id,
      hostedAvatarDisplayName: avatar.displayName,
      hostedAvatarImageUrl: avatar.imageUrl,
    });
  }

  async function selectSegmentedVideo(value: string) {
    if (value.startsWith("opentalking:")) {
      const assetId = value.slice("opentalking:".length);
      const asset = OPENTALKING_MOTION_ASSETS.find((motion) => motion.id === assetId);
      if (!asset) return;
      onAvatarDisplayConfigChange({
        ...avatarDisplayConfig,
        segmentedPresetId: "custom-upload",
        segmentedAvatarId: asset.id,
        segmentedAvatarActionId: `builtin:opentalking:${asset.id}`,
      });
      return;
    }
    if (value.startsWith("builtin:")) {
      onAvatarDisplayConfigChange({
        ...avatarDisplayConfig,
        segmentedVideoId: value.slice("builtin:".length),
        segmentedAvatarActionId: value,
      });
      return;
    }
    if (!value.startsWith("motion:")) return;
    const motionBaseId = value.slice("motion:".length);
    const motionBase = motionBaseCatalog.find((motion) => motion.avatar_action_id === motionBaseId);
    if (!motionBase) return;
    const visualIdentityId = motionBase.avatar_id;
    setAvatarActionCatalogState("loading");
    setAvatarActionCatalogNotice("正在切换当前动作底片");
    try {
      const response = await fetch("/api/avatar-assets/selections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatarId: visualIdentityId, avatarActionId: motionBaseId }),
      });
      const payload = await readJsonResponse<{ error?: string }>(
        response,
        "动作底片切换请求失败",
      );
      if (!response.ok) throw new Error(payload.error || "切换当前动作底片失败");
      onAvatarDisplayConfigChange({
        ...avatarDisplayConfig,
        segmentedAvatarId: visualIdentityId,
        segmentedAvatarActionId: motionBaseId,
      });
      setAvatarActionCatalogState("ready");
      setAvatarActionCatalogNotice("已设为当前动作底片");
    } catch (error) {
      setAvatarActionCatalogState("error");
      setAvatarActionCatalogNotice(error instanceof Error ? error.message : "切换当前动作底片失败");
    }
  }

  function selectSegmentedAvatarAsset(avatar: AvatarAsset, action: AvatarAction | null) {
    if (action && !action.avatarActionId.startsWith("builtin:")) {
      void selectSegmentedVideo(`motion:${action.avatarActionId}`);
      return;
    }
    onAvatarDisplayConfigChange({
      ...avatarDisplayConfig,
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: avatar.avatarId,
      segmentedDisplayName: avatar.displayName,
      segmentedAvatarActionId: action?.avatarActionId
        ?? (avatar.ownerId ? `builtin:identity-static:${avatar.avatarId}` : ""),
    });
  }

  function confirmAvatarAssetDeletion() {
    if (!pendingAvatarAssetDeletion) return;
    const nextPreferences = hideAvatarLibraryAsset(
      assetLibraryPreferences,
      pendingAvatarAssetDeletion.kind,
      pendingAvatarAssetDeletion.id,
    );
    setAssetLibraryPreferences(nextPreferences);
    persistAvatarAssetLibraryPreferences(nextPreferences);
    const nextDisplayConfig = resolveAvatarDisplayConfigAfterDeletion(
      avatarDisplayConfig,
      pendingAvatarAssetDeletion,
    );
    if (nextDisplayConfig !== avatarDisplayConfig) onAvatarDisplayConfigChange(nextDisplayConfig);
    setAvatarActionCatalogNotice(`已从本机资产库删除「${pendingAvatarAssetDeletion.label}」`);
    setPendingAvatarAssetDeletion(null);
  }

  async function toggleVoicePreview(provider: TtsProvider, voice: TtsVoice, voiceLabel: string) {
    if (publicVoiceEnabled) return;
    const isCurrentPreview = previewVoice === voice;
    if (isCurrentPreview && previewState === "loading") {
      previewRequestRef.current?.abort();
      previewRequestRef.current = null;
      setPreviewState("idle");
      setPreviewVoice(null);
      setPreviewNotice("已取消试听");
      return;
    }
    if (isCurrentPreview && previewState === "playing") {
      previewAudioRef.current?.pause();
      setPreviewState("idle");
      setPreviewVoice(null);
      setPreviewNotice("已停止试听");
      return;
    }

    previewRequestRef.current?.abort();
    previewAudioRef.current?.pause();
    previewAudioRef.current = null;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = "";
    setPreviewVoice(voice);
    setPreviewState("loading");
    setPreviewNotice(`正在生成「${voiceLabel}」试听…`);
    const controller = new AbortController();
    previewRequestRef.current = controller;
    try {
      const params = new URLSearchParams({
        provider,
        voice,
        speech_rate: String(ttsSpeechRate),
        dialect: provider === "bailian" ? bailianDialect : voice === DIALECT_TTS_VOICE ? ttsDialect : "",
      });
      const response = await fetch(`/api/tts/preview?${params.toString()}`, {
        signal: controller.signal,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null;
        throw new Error(payload?.error ?? "音色试听生成失败");
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      const audio = new Audio(url);
      audio.volume = playbackVolume / 100;
      previewAudioRef.current = audio;
      audio.onended = () => {
        setPreviewState("idle");
        setPreviewVoice(null);
        setPreviewNotice(`「${voiceLabel}」试听结束`);
      };
      audio.onerror = () => {
        setPreviewState("idle");
        setPreviewVoice(null);
        setPreviewNotice("音频播放失败，请稍后重试");
      };
      await audio.play();
      previewRequestRef.current = null;
      setPreviewState("playing");
      setPreviewNotice(`正在播放「${voiceLabel}」`);
    } catch (error) {
      if (controller.signal.aborted) return;
      previewRequestRef.current = null;
      setPreviewState("idle");
      setPreviewVoice(null);
      setPreviewNotice(error instanceof Error ? error.message : "音色试听生成失败");
    }
  }

  const selectedVoice = findTtsVoice(ttsVoice);
  const isAvatarMode = experienceMode === "avatar";
  const isVoiceMode = experienceMode === "voice";
  const disabledExperienceModes: ExperienceMode[] = avatarConfigLocked
    ? experienceMode === "avatar" ? ["voice"] : ["avatar"]
    : [];
  const selectedVoiceLabel = ttsProvider === "doubao"
    ? selectedVoice?.label ?? "自定义音色"
    : bailianVoiceLabel;
  const selectedSegmentedVideo = VIDEO_BASE_CHOICES.find((choice) => choice.id === avatarDisplayConfig.segmentedVideoId) ?? VIDEO_BASE_CHOICES[0];
  const selectedBuiltinVideoId = avatarDisplayConfig.segmentedAvatarActionId.startsWith("builtin:")
    ? avatarDisplayConfig.segmentedAvatarActionId.slice("builtin:".length)
    : "";
  const selectedOpenTalkingMotionId = selectedBuiltinVideoId.startsWith("opentalking:")
    ? selectedBuiltinVideoId.slice("opentalking:".length)
    : "";
  const selectedOpenTalkingMotion = OPENTALKING_MOTION_ASSETS.find((motion) => motion.id === selectedOpenTalkingMotionId);
  const selectedOpenTalkingIdentity = OPENTALKING_AVATAR_CATALOG.find(
    (identity) => identity.id === avatarDisplayConfig.segmentedAvatarId,
  );
  const selectedIdentityOnly = Boolean(selectedOpenTalkingIdentity && !avatarDisplayConfig.segmentedAvatarActionId);
  const selectedMotionBaseId = selectedBuiltinVideoId
    ? ""
    : avatarDisplayConfig.segmentedAvatarActionId;
  const selectedProjectBuiltinAction = getBuiltinAvatarAction(avatarDisplayConfig.segmentedAvatarActionId);
  const selectedMotionBase = motionBaseCatalog.find((motionBase) => motionBase.avatar_action_id === selectedMotionBaseId);
  const managedAvatarSelected = avatarDisplayConfig.segmentedAvatarId.startsWith("avatar-");
  const currentCatalogAction = segmentedAvatarCatalog
    .find((avatar) => avatar.avatarId === avatarDisplayConfig.segmentedAvatarId && !avatar.deletedAt)
    ?.actions.find((action) => action.avatarActionId === avatarDisplayConfig.segmentedAvatarActionId);
  const selectedMotionName = managedAvatarSelected
    ? currentCatalogAction?.displayName ?? "正在加载动作"
    : selectedProjectBuiltinAction
    ? selectedProjectBuiltinAction.name
    : selectedOpenTalkingMotion
    ? `${selectedOpenTalkingMotion.name} · 配套动作`
    : selectedMotionBase
      ? avatarActionLabel(selectedMotionBase)
      : MOTION_ASSET_LABELS[selectedSegmentedVideo.id] ?? "已选动作";
  const selectedSavedMotionPlayback = selectedMotionBase
    ? selectAvatarActionRendition(selectedMotionBase, avatarDisplayConfig.ratio)
    : null;
  const selectedMotionPreviewUrl = managedAvatarSelected
    ? currentCatalogAction?.videoUrl ?? ""
    : selectedProjectBuiltinAction?.videoUrl
    ?? selectedOpenTalkingMotion?.motionVideoUrl
    ?? getBuiltinMotionPreviewUrl(selectedBuiltinVideoId)
    ?? (selectedSavedMotionPlayback?.rendition.artifact_id
      ? `/api/avatar-assets/artifacts/${encodeURIComponent(selectedSavedMotionPlayback.rendition.artifact_id)}`
      : "");
  const avatarDisplayName = selectedHostedAvatar?.displayName
    ?? avatarDisplayConfig.hostedAvatarDisplayName
    ?? "已选托管形象";
  const avatarPreviewImage = selectedHostedAvatar?.imageUrl
    ?? avatarDisplayConfig.hostedAvatarImageUrl
    ?? "";
  const avatarPreviewService = avatarDisplayConfig.renderPath === "hosted"
    ? "实时托管 · 已选形象"
    : selectedIdentityOnly
      ? `分段式合成 · ${selectedOpenTalkingIdentity?.name} · 仅口型对齐`
      : `分段式合成 · ${selectedMotionName}`;
  const avatarRuntimeImplemented = avatarDisplayConfig.renderPath === "hosted" && avatarDisplayConfig.provider === "anam";
  const avatarPreviewState = avatarRuntimeImplemented
    ? "READY"
    : selectedIdentityOnly
      ? "LIP SYNC ONLY"
    : selectedMotionBaseId || selectedBuiltinVideoId || avatarDisplayConfig.segmentedVideoId
      ? "MOTION SELECTED"
      : "SELECT ASSET";
  const avatarModeLabel = avatarDisplayConfig.renderPath === "hosted" ? "实时托管" : "分段式合成";
  const personaManageAvatarId = avatarPersonaSelectionId({
    renderPath: avatarDisplayConfig.renderPath,
    avatarProfileId: avatarDisplayConfig.avatarProfileId,
    segmentedAvatarId: avatarDisplayConfig.segmentedAvatarId,
  });
  const personaManageAvatarName = avatarDisplayConfig.renderPath === "hosted"
    ? avatarDisplayName
    : avatarDisplayConfig.segmentedDisplayName || personaManageAvatarId || "";
  const {
    linkedPersona,
    linkedPersonaState,
    personaOptions,
    switchState,
    switchNotice,
    switchPersona,
  } = usePersonaLink(open ? personaManageAvatarId : null, personaManageAvatarName, open);
  const selectedPersonaLabel = linkedPersona?.personaName ?? "未关联";
  const workbenchTokens = workbenchSurfaceTokens(workbenchVisualPreferences);
  const sessionWorkbenchStyle = sessionWorkbench ? {
    "--panel-surface-alpha": workbenchTokens.surfaceAlpha,
    "--panel-highlight-alpha": workbenchTokens.highlightAlpha,
    "--panel-soft-alpha": workbenchTokens.softAlpha,
    "--panel-blur": workbenchTokens.blur,
  } as CSSProperties : undefined;

  return (
    <>
      {!embedded && <div className={`drawer-backdrop ${open ? "open" : ""}`} data-variant={variant} onClick={onClose} />}
      <aside
        className={`drawer ${embedded ? "drawer-embedded open" : sessionWorkbench ? `drawer-session-workbench ${open ? "open" : ""}` : open ? "open" : ""}`}
        data-variant={variant}
        data-session-mode={sessionWorkbench ? experienceMode : undefined}
        role={embedded ? "region" : "dialog"}
        aria-modal={embedded ? undefined : true}
        aria-hidden={embedded ? undefined : !open}
        inert={embedded ? undefined : !open}
        aria-labelledby={embedded ? undefined : "config-studio-title"}
        aria-label={embedded ? t("高级会话配置") : undefined}
        style={sessionWorkbenchStyle}
      >
        {!embedded && <header className="drawer-header">
          <div className="drawer-title-lockup">
            <span className="drawer-brand-mark" aria-hidden="true"><Sparkles /></span>
            <div>

              <h2 id="config-studio-title">{sessionWorkbench ? t("会话配置工作台") : t("体验配置")}</h2>
            </div>
          </div>
          <div className="drawer-header-meta">
            {sessionWorkbench
              ? <span className="drawer-session-mode"><i />{isAvatarMode ? t("数字人") : t("对话")}{t(" · 通话中")}</span>
              : <span className="drawer-save-state"><i />{t("本机自动保存")}</span>}
            <button className="icon-btn" type="button" aria-label={t("关闭设置")} onClick={onClose}>
              <X />
            </button>
          </div>
        </header>}

        <div className="drawer-workspace">
          <div className="drawer-config-pane">
            {!embedded && <div className="drawer-tabs" role="tablist" aria-label={t("设置分类")}>
              {CONFIG_TABS.map(({ id, label, icon: Icon }) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === id}
                  data-active={activeTab === id}
                  key={id}
                  onClick={() => setActiveTab(id)}
                >
                  <Icon aria-hidden="true" />
                  {t(label)}
                </button>
              ))}
            </div>}

            <div className="drawer-body" role="tabpanel">
              {activeTab === "display" && (
                <div className="drawer-tab-content">
                  <div className="display-mode-picker">
                    {sessionWorkbench ? (
                      <div className="session-workbench-mode-lock" data-mode={experienceMode} role="status">
                        <span>{isAvatarMode ? <UserRound /> : <Radio />}</span>
                        <span><small>{t("当前会话呈现")}</small><strong>{isAvatarMode ? t("数字人") : t("对话")}</strong></span>
                        <em><i />{t("已锁定")}</em>
                      </div>
                    ) : (
                      <ExperienceModeSwitch
                        value={experienceMode}
                        onChange={onExperienceModeChange}
                        disabledModes={disabledExperienceModes}
                        compact
                        descriptionsAsTooltip
                        ariaLabel={t("设置展示模式")}
                      />
                    )}
                    {avatarConfigLocked && !sessionWorkbench && <div className="display-config-lock-notice" role="status"><Clock3 />{t("当前展示模式已绑定到本次会话，结束后可重新选择")}</div>}
                  </div>

                  {isVoiceMode ? (
                    <section className="config-card mode-specific-card" data-mode="voice">
                      <div className="config-card-heading">
                        <span className="config-step"><Radio /></span>
                        <div><h4>{t("对话模式视觉")}</h4></div>
                        <InfoHint text={t("配置声场主题与语音反馈动画强度。")} />
                      </div>
                      <div className="drawer-row">
                        <div className="drawer-row-label"><span>{t("语音视觉主题 ")}<InfoHint text={t("选择通话主画面的声场表达。")} /></span></div>
                        <SelectMenu value={voiceVisualTheme} localizeLabels options={VISUAL_THEME_OPTIONS} ariaLabel={t("语音视觉主题")} onChange={onVoiceVisualThemeChange} />
                      </div>
                      <div className="drawer-row">
                        <div className="drawer-row-label"><span>{t("动态强度")}</span><span className="drawer-row-hint">{t("波形与呼吸动画 ")}{classicMotionIntensity}%</span></div>
                        <input type="range" min={20} max={100} value={classicMotionIntensity} aria-label={t("对话模式动态强度")} disabled={reducedMotion} onChange={(event) => setClassicMotionIntensity(Number(event.target.value))} />
                      </div>
                    </section>
                  ) : sessionWorkbench && avatarConfigLocked ? (
                    <section className="config-card session-avatar-lock-card">
                      <div className="config-card-heading">
                        <span className="config-step"><Video /></span>
                        <div><h4>{t("当前数字人呈现")}</h4></div>
                        <span className="avatar-config-save-state"><i />{t("运行中")}</span>
                      </div>
                      <div className="session-avatar-lock-summary">
                        <span><small>{t("驱动方式")}</small><strong>{t(avatarModeLabel)}</strong></span>
                        <span><small>{avatarDisplayConfig.renderPath === "hosted" ? t("数字人形象") : t("数字人动作")}</small><strong>{avatarDisplayConfig.renderPath === "hosted" ? avatarDisplayName : selectedMotionName}</strong></span>
                      </div>
                      <p>{t("当前人物与驱动服务已经绑定到本次通话；结束通话后可在首页工作台重新选择。")}</p>
                    </section>
                  ) : (
                    <>
                      <section className="config-card mode-specific-card avatar-asset-overview" data-mode="avatar">
                        <div className="config-card-heading">
                          <span className="config-step"><Video /></span>
                          <div><h4>{t("数字人资产配置")}</h4></div>
                          <InfoHint text={t("选择渲染方式与已经可以使用的资产。")} />
                          <span className="avatar-config-save-state"><i />{t("选择已保存")}</span>
                        </div>
                        <div className="avatar-render-mode-grid" role="group" aria-label={t("数字人渲染模式")}>
                          {AVATAR_RENDER_PATH_OPTIONS.map((path) => (
                            <button type="button" key={path.value} data-selected={avatarDisplayConfig.renderPath === path.value} aria-pressed={avatarDisplayConfig.renderPath === path.value} disabled={avatarConfigLocked} onClick={() => onAvatarDisplayConfigChange({ ...avatarDisplayConfig, renderPath: path.value })}>
                              <span className="avatar-render-mode-index">{path.value === "hosted" ? <UserRound /> : <Film />}</span>
                              <span><strong>{<LocalizedText text={path.label} />}</strong><small>{<LocalizedText text={path.description} />}</small></span>
                              <i>{avatarDisplayConfig.renderPath === path.value ? <Check /> : null}</i>
                            </button>
                          ))}
                        </div>
                      </section>

                      <section className="config-card avatar-asset-catalog-card">
                        <div className="config-card-heading">
                          <span className="config-step">{avatarDisplayConfig.renderPath === "hosted" ? <UserRound /> : <Film />}</span>
                          <div>
                            <h4>{avatarDisplayConfig.renderPath === "hosted" ? t("数字人形象资产库") : t("Avatar 资产")}</h4>
                            <p>{avatarDisplayConfig.renderPath === "hosted" ? t("选择实时托管使用的形象") : t("每个 Avatar 包含形象和所属动作；左右浏览不会改变配置，点击后才更新")}</p>
                          </div>
                          <span className="avatar-library-count">{avatarDisplayConfig.renderPath === "hosted" ? t("实时托管") : t("分段式合成")}</span>
                        </div>
                        {avatarDisplayConfig.renderPath === "hosted" ? (
                          <HostedAvatarCatalog
                            active={open && isAvatarMode}
                            disabled={avatarConfigLocked}
                            selectedAvatarId={avatarDisplayConfig.avatarProfileId}
                            onSelect={selectHostedAvatar}
                          />
                        ) : (
                          <div className="segmented-asset-config">
                            <Link className="avatar-asset-create-card" href="/avatars/create?task=action">
                              <span><Plus /></span>
                              <span><strong>{t("创建 Avatar 动作")}</strong><small>{t("进入 Avatar 创建页 · 动作任务")}</small></span>
                              <Sparkles />
                            </Link>
                            <span className="avatar-asset-library-status" data-state={motionBaseCatalogState} role="status"><i />{motionBaseCatalogNotice || t("正在读取 Avatar 资产")}</span>
                            <SegmentedAvatarAssetPicker
                              avatars={segmentedAvatarCatalog}
                              selectedAvatarId={avatarDisplayConfig.segmentedAvatarId}
                              selectedActionId={avatarDisplayConfig.segmentedAvatarActionId}
                              disabled={avatarConfigLocked || motionBaseCatalogState === "loading"}
                              active={open && !reducedMotion}
                              onSelect={selectSegmentedAvatarAsset}
                            />
                          </div>
                        )}
                      </section>

                    <p className="avatar-config-boundary-note">{t("此处可选择待适配动作；形象与动作的创建、草稿和生成任务统一在数字人工作台完成。")}</p>
                    </>
                  )}
                </div>
              )}

              {activeTab === "general" && (
                <div className="drawer-tab-content">
                  <section className="config-card">
                    <BottomVoiceStylePicker />
                  </section>
                  <section className="config-card">
                    <div className="config-card-heading"><span className="config-step"><Settings2 /></span><div><h4>{t("界面主题")}</h4><p>{t("应用于首页、设置与数字人资产页面")}</p></div><InfoHint text={t("主题保存在本机，并在所有页面保持一致。")} /></div>
                    <div className="app-theme-grid" role="radiogroup" aria-label={t("通用界面主题")}>
                      {APP_THEME_OPTIONS.map((theme) => (
                        <button
                          type="button"
                          role="radio"
                          aria-checked={appTheme === theme.value}
                          data-selected={appTheme === theme.value}
                          key={theme.value}
                          onClick={() => onAppThemeChange(theme.value)}
                        >
                          <span className="app-theme-swatches" aria-hidden="true">
                            {theme.colors.map((color) => <i key={color} style={{ background: color }} />)}
                          </span>
                          <span><strong>{<LocalizedText text={theme.label} />}</strong><small>{<LocalizedText text={theme.description} />}</small></span>
                          <i className="app-theme-check">{appTheme === theme.value ? <Check /> : null}</i>
                        </button>
                      ))}
                    </div>
                  </section>
                  <section className="config-card">
                    <div className="config-card-heading"><span className="config-step"><Sparkles /></span><div><h4>{t("动态与辅助")}</h4></div><InfoHint text={t("管理工作台的配置预览动态。")} /></div>
                    <div className="drawer-row"><div className="drawer-row-label"><span>{t("减少预览动态")}</span><InfoHint text={t("停止首页轮播、设置预览和自动口型视频；不改变活动会话中的 Renderer。")} /></div><label className="switch"><input type="checkbox" checked={reducedMotion} onChange={(event) => onReducedMotionChange(event.target.checked)} /><span className="switch-track" /></label></div>
                  </section>
                </div>
              )}

              {activeTab === "model" && (
                <div className="drawer-tab-content">
                    <div className="drawer-panel-intro">
                      <span>MODEL &amp; PERSONA</span>
                      <h3>{t("模型指令与角色配置")}</h3>
                      <p>{t("选择国内外模型或定义兼容接口，再配置共用的系统提示词与 Persona。")}</p>
                    </div>
                    <section className="config-card">
                      <div className="config-card-heading">
                        <span className="config-step"><BrainCircuit /></span>
                        <div><h4>{t("模型供应商")}</h4></div>
                        <InfoHint text={t("选择模型服务商后，会同步推荐模型、协议和接口默认值。")} />
                      </div>
                      <div className="model-provider-select-row">
                        <SelectMenu value={modelProvider} localizeLabels options={MODEL_PROVIDER_MENU_OPTIONS} ariaLabel={t("模型供应商")} onChange={selectModelProvider} />
                        <span className="provider-chip"><i />{selectedModelProvider.region}</span>
                        <InfoHint text={`${selectedModelProvider.label}：${selectedModelProvider.description}`} />
                      </div>
                    </section>

                    <details className="config-card config-card-disclosure">
                      <summary className="config-card-heading">
                        <span className="config-step"><Settings2 /></span>
                        <div><h4>{t("模型与接口定义")}</h4><p>{modelId || t("未选择模型")} · {<LocalizedText text={MODEL_PROTOCOL_OPTIONS.find((option) => option.value === modelProtocol)?.label} />}</p></div>
                        <ChevronDown className="config-disclosure-chevron" />
                      </summary>
                      <div className="config-disclosure-body">
                        <div className="model-interface-form">
                          <label>
                            <span>{t("推荐模型")}</span>
                            <SelectMenu value={selectedModelProvider.models.some((model) => model.value === modelId) ? modelId : selectedModelProvider.models[0].value} options={selectedModelProvider.models} ariaLabel={t("推荐模型")} onChange={setModelId} />
                          </label>
                          <label>
                            <span>{t("协议")}</span>
                            <SelectMenu value={modelProtocol} localizeLabels options={MODEL_PROTOCOL_OPTIONS} ariaLabel={t("大模型接口协议")} onChange={(value) => setModelProtocol(value as ModelProtocol)} />
                          </label>
                          <label className="model-field-wide"><span>Model ID</span><input value={modelId} aria-label={t("大模型 Model ID")} placeholder={t("例如 qwen3.7-flash")} onChange={(event) => setModelId(event.target.value)} /></label>
                          {modelProvider === "bailian" && <label className="model-field-wide"><span>Workspace ID</span><input value={modelWorkspaceId} aria-label={t("百炼 Workspace ID")} placeholder={t("业务空间 ID")} onChange={(event) => setModelWorkspaceId(event.target.value)} /></label>}
                          <label className="model-field-wide"><span>Base URL</span><input value={modelBaseUrl} aria-label={t("大模型 Base URL")} placeholder="https://api.example.com/v1" onChange={(event) => setModelBaseUrl(event.target.value)} /></label>
                          <label className="model-field-wide"><span className="model-field-label">{t("API Key 环境变量 ")}<InfoHint text={t("这里只定义服务端变量名，不在浏览器保存真实密钥。")} /></span><input value={modelApiKeyEnv} aria-label={t("API Key 环境变量")} placeholder="VOICEAGENT_LLM_API_KEY" onChange={(event) => setModelApiKeyEnv(event.target.value)} /></label>
                        </div>
                        <p className="model-runtime-note" data-ready={modelProtocol === "openai-chat-completions" ? "true" : "false"}><BrainCircuit />{modelProtocol === "openai-chat-completions" ? t("当前 Python 运行时可复用 OpenAI-compatible 客户端；发布 Profile API 后动态生效。") : t("接口定义已保存；此原生协议还需要新增服务端 Adapter 后才能运行。")}</p>
                      </div>
                    </details>
                    <details className="config-card config-card-disclosure">
                      <summary className="config-card-heading">
                        <span className="config-step"><BrainCircuit /></span>
                        <div><h4>{t("系统提示词")}</h4><p>System Prompt · {systemPrompt.length}{t(" 字符")}</p></div>
                        <ChevronDown className="config-disclosure-chevron" />
                      </summary>
                      <div className="config-disclosure-body">
                        <label className="model-prompt-editor">
                          <span>{t("决定模型的基础身份、边界和回复规则")}</span>
                          <textarea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} aria-label={t("系统提示词")} />
                          <small>{systemPrompt.length}{t(" 字符 · 发布 Profile API 后生效")}</small>
                        </label>
                      </div>
                    </details>
                    <section className="config-card">
                      <div className="config-card-heading">
                        <span className="config-step"><FileText /></span>
                        <div><h4>Persona</h4></div>
                        <InfoHint text={t("关联的 Persona 会按 OpenClaw 角色文件顺序注入当前会话的系统提示词；在 Persona 库中编辑后下一轮对话生效，USER 与 MEMORY 仍由用户和会话单独管理。")} />
                      </div>
                      <div className="persona-select-row">
                        <SelectMenu
                          ariaLabel={t("选择 Persona")}
                          value={linkedPersona?.personaId ?? ""}
                          options={personaSelectOptions(personaOptions, linkedPersona?.personaId ?? null)}
                          cardOptions
                          disabled={switchState === "busy"}
                          onChange={(value) => {
                            if (value === PERSONA_CREATE_OPTION_VALUE) {
                              window.open(
                                `/personas?avatar_id=${encodeURIComponent(personaManageAvatarId ?? "")}&avatar_display_name=${encodeURIComponent(personaManageAvatarName)}`,
                                "_blank",
                                "noreferrer",
                              );
                              return;
                            }
                            if (!value || value === linkedPersona?.personaId) return;
                            void switchPersona(value);
                          }}
                        />
                        <a
                          className="config-primary-button"
                          href={`/personas?avatar_id=${encodeURIComponent(personaManageAvatarId ?? "")}&avatar_display_name=${encodeURIComponent(personaManageAvatarName)}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {t("管理 Persona")}</a>
                      </div>
                      {linkedPersonaState === "loading" && (
                        <p className="config-note">{t("正在读取当前数字人的默认 Persona…")}</p>
                      )}
                      {linkedPersonaState === "error" && (
                        <p className="config-note" role="alert">{t("Persona 配置暂时无法读取，运行时将保留基础系统提示词。")}</p>
                      )}
                      {switchNotice && (
                        <p className="config-note" role={switchState === "error" ? "alert" : "status"}>{switchNotice}</p>
                      )}
                    </section>
                </div>
              )}

              {activeTab === "voice" && (
                <div className="drawer-tab-content">
                  <div className="drawer-panel-intro">

                    <h3>{t("供应商、音色与试听")}</h3>
                    <p>{t("先选择供应商，再从对应目录选择内置或克隆音色。")}</p>
                  </div>
                  <section className="config-card">
                    <div className="config-card-heading">
                      <span className="config-step"><AudioLines /></span>
                      <div><h4>{t("语音供应商")}</h4><p>{t("当前选择：")}{<LocalizedText text={TTS_PROVIDER_OPTIONS.find((provider) => provider.value === ttsProvider)?.label} />}</p></div>
                      <InfoHint text={t("支持阿里云百炼与火山引擎；切换后会显示对应音色目录。")} />
                    </div>
                    <div className="voice-provider-select-row">
                      <SelectMenu
                        value={ttsProvider}
                        options={TTS_PROVIDER_OPTIONS}
                        ariaLabel={t("语音供应商选择")}
                        onChange={setTtsProvider}
                      />
                    </div>
                  </section>

                  <div className="voice-library-grid">
                    <details className="config-card voice-library-disclosure">
                      <summary className="config-card-heading">
                        <span className="config-step"><Mic2 /></span>
                        <div><h4>{t("内置音色")}</h4><p>{ttsProvider === "bailian" ? "" + (BAILIAN_TTS_VOICE_OPTIONS.length) + t(" 个百炼音色") : "" + (TTS_VOICE_OPTIONS.length) + t(" 个火山音色")}{publicVoiceEnabled ? t(" · 公开体验请在会话中试听") : !ttsPreviewAvailable ? t(" · 服务重启后启用真实试听") : ""}</p></div>
                        <ChevronDown className="voice-library-chevron" />
                      </summary>
                      <div className="voice-catalog-list" aria-label={t("内置音色列表")}>
                        {(ttsProvider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS : TTS_VOICE_OPTIONS).map((voice) => {
                          const selected = ttsProvider === "bailian" ? bailianVoice === voice.value : ttsVoice === voice.value;
                          const previewing = previewVoice === voice.value;
                          const isLoading = previewing && previewState === "loading";
                          const isPlaying = previewing && previewState === "playing";
                          return <div className="provider-voice-row" data-selected={selected} key={voice.value}>
                            <button type="button" className="provider-voice-select" aria-pressed={selected} onClick={() => ttsProvider === "bailian" ? selectBailianVoice(voice.value, voice.label) : onTtsVoiceChange(voice.value)}>
                              <span className="provider-voice-avatar">{selected ? <Check /> : voice.label.slice(0, 1)}</span>
                              <span><strong>{<LocalizedText text={voice.label} />}</strong><small>{selected ? t("已选中 · ") + (voice.description) + "" : voice.description}</small></span>
                            </button>
                            <button type="button" className="provider-voice-preview" aria-label={"" + (isPlaying ? "停止试听" : "试听") + " " + (voice.label) + ""} disabled={publicVoiceEnabled || (previewState === "loading" && !previewing)} onClick={() => toggleVoicePreview(ttsProvider, voice.value, voice.label)}>
                              {isLoading ? <span className="preview-spinner" /> : isPlaying ? <Square /> : <Play />}
                            </button>
                          </div>;
                        })}
                      </div>
                    </details>

                    {!publicVoiceEnabled && <VoiceClonePanel
                      provider={ttsProvider}
                      selectedVoice={bailianVoice}
                      previewVoice={previewVoice}
                      previewState={previewState}
                      onSelect={selectBailianVoice}
                      onPreview={(voiceId, label) => toggleVoicePreview("bailian", voiceId, label)}
                    />}
                  </div>

                  <section className="config-card">
                    <div className="config-card-heading"><span className="config-step"><Radio /></span><div><h4>{t("方言与播放")}</h4></div><InfoHint text={t("可选方言会随供应商和音色变化。")} /></div>
                    <div className="drawer-row">
                      <div className="drawer-row-label"><span>{t("方言 ")}<InfoHint text={ttsProvider === "bailian" ? "龙安欢 V3 支持多种方言。" : "Vivi 2.0 支持东北、陕西、四川。"} /></span></div>
                      {ttsProvider === "bailian" ? <SelectMenu value={bailianDialect} localizeLabels options={BAILIAN_DIALECT_OPTIONS} ariaLabel={t("百炼 TTS 方言")} placement="top" onChange={setBailianDialect} /> : <SelectMenu value={ttsDialect} localizeLabels options={TTS_DIALECT_OPTIONS} ariaLabel={t("豆包 TTS 方言")} placement="top" onChange={onTtsDialectChange} />}
                    </div>
                    <div className="drawer-row"><div className="drawer-row-label"><span>{t("语速")}</span><span className="drawer-row-hint">{t("相对默认 ")}{ttsSpeechRate === 0 ? t("不变") : `${ttsSpeechRate > 0 ? "+" : ""}${ttsSpeechRate}%`}</span></div><input type="range" min={-50} max={100} value={ttsSpeechRate} aria-label={t("TTS 语速")} onChange={(event) => onTtsSpeechRateChange(Number(event.target.value))} /></div>
                    <div className="drawer-row"><div className="drawer-row-label"><span>{t("播放音量")}</span><span className="drawer-row-hint">{t("本地播放 ")}{playbackVolume}%</span></div><input type="range" min={0} max={100} value={playbackVolume} aria-label={t("本地播放音量")} onChange={(event) => { const volume = Number(event.target.value); setPlaybackVolume(volume); setVolume(volume / 100); writeConversationPreferences({ ...readConversationPreferences(), volume }); }} /></div>
                    {(previewNotice || ttsConfigStatus) && <p className="voice-config-status" role="status">{previewNotice || localizedTtsStatus(ttsConfigStatus)}</p>}
                  </section>
                </div>
              )}

              {activeTab === "tools" && (
                <div className="drawer-tab-content">
                  <div className="drawer-panel-intro">

                    <h3>{t("工具调用与自定义能力")}</h3>
                    <p>{t("内置工具由服务端注册；自定义工具先在本机建立草稿。")}</p>
                  </div>
                  <section className="config-card">
                    <div className="config-card-heading"><span className="config-step"><Wrench /></span><div><h4>{t("内置工具")}</h4></div><InfoHint text={t("这些能力来自当前服务端 Tool Registry。")} /></div>
                    <div className="builtin-tool-row"><span><Clock3 /></span><span><strong>{t("时间查询")}</strong><small>{t("ClockTool · 已接入")}</small></span><i>{t("可选")}</i></div>
                    <div className="builtin-tool-row"><span><Globe2 /></span><span><strong>{t("网页搜索")}</strong><small>{t("WebSearchTool · 凭据配置后使用")}</small></span><i>{t("可选")}</i></div>
                    <div className="builtin-tool-row"><span><Wrench /></span><span><strong>{t("计算器 / 单位换算 / 文本统计")}</strong><small>{t("内置工具 · 在角色工具设置中选择")}</small></span><i>{t("可选")}</i></div>
                  </section>
                  <details className="config-card config-card-disclosure">
                    <summary className="config-card-heading"><span className="config-step"><Plus /></span><div><h4>{t("自定义工具")}</h4><p>{customTools.length ? "" + (customTools.length) + t(" 个草稿") : "HTTP / MCP / OpenAPI"}</p></div><ChevronDown className="config-disclosure-chevron" /></summary>
                    <div className="config-disclosure-body">
                      <div className="custom-tool-form">
                        <label><span>{t("工具名称")}</span><input value={toolName} placeholder={t("例如 query_order")} onChange={(event) => setToolName(event.target.value)} /></label>
                        <label><span>Endpoint</span><input value={toolEndpoint} placeholder="https://api.example.com/tools/query" onChange={(event) => setToolEndpoint(event.target.value)} /></label>
                        <button type="button" disabled={!toolName.trim() || !toolEndpoint.trim()} onClick={() => { setCustomTools((tools) => [...tools, { id: crypto.randomUUID(), name: toolName.trim(), endpoint: toolEndpoint.trim() }]); setToolName(""); setToolEndpoint(""); }}><Plus />{t("添加工具")}</button>
                      </div>
                      {customTools.length ? <div className="custom-tool-list">{customTools.map((tool) => <div key={tool.id}><span><Wrench /><span><strong>{<LocalizedText text={tool.name} />}</strong><small>{tool.endpoint}</small></span></span><button type="button" aria-label={t("移除工具 ") + (tool.name) + ""} onClick={() => setCustomTools((tools) => tools.filter((item) => item.id !== tool.id))}><Trash2 /></button></div>)}</div> : <p className="config-note">{t("尚未添加自定义工具。发布前需要 Schema 校验、鉴权和权限确认。")}</p>}
                    </div>
                  </details>
                </div>
              )}

              {activeTab === "conversation" && (
                <div className="drawer-tab-content">
                  <div className="drawer-panel-intro">

                    <h3>{t("实时交互策略")}</h3>
                    <p>{t("调整打断、收音和当前会话的运行方式。")}</p>
                  </div>
                  <section className="config-card">
                    <div className="config-card-heading">
                      <span className="config-step"><MessageCircle /></span>
                      <div><h4>{t("对话行为")}</h4></div>
                      <InfoHint text={t("打断与浏览器收音设置会立即应用到当前会话。")} />
                    </div>
                    <div className="drawer-row">
                      <div className="drawer-row-label">
                        <span>{t("允许随时打断 ")}<InfoHint text={t("AI 播放期间继续收音，由服务端判断是否打断。")} /></span>
                      </div>
                      <label className="switch">
                        <input type="checkbox" checked={allowBargeIn} onChange={(event) => { setAllowBargeIn(event.target.checked); setBargeInMuted(!event.target.checked); writeConversationPreferences({ ...readConversationPreferences(), allowBargeIn: event.target.checked }); }} />
                        <span className="switch-track" />
                      </label>
                    </div>
                    <div className="drawer-row">
                      <div className="drawer-row-label">
                        <span>{t("浏览器降噪 / 回声消除 ")}<InfoHint text={t("通话中切换时会重新建立麦克风采集。")} /></span>
                      </div>
                      <label className="switch">
                        <input type="checkbox" checked={noiseSuppressionEnabled} onChange={(event) => { setNoiseSuppressionEnabled(event.target.checked); setNoiseSuppression(event.target.checked); writeConversationPreferences({ ...readConversationPreferences(), noiseSuppression: event.target.checked }); }} />
                        <span className="switch-track" />
                      </label>
                    </div>
                  </section>
                  <section className="config-card">
                    <div className="config-card-heading">
                      <span className="config-step"><Clock3 /></span>
                      <div><h4>{t("当前会话")}</h4></div>
                      {sessionId ? <span className="provider-chip"><i />{t("已建立实时连接")}</span> : <InfoHint text={t("会话 ID 会在开始通话后生成。")} />}
                    </div>
                    <div className="session-card-row">
                      <span className="session-id-text">{sessionId ?? t("尚未建立会话")}</span>
                      <button type="button" className="copy-btn" data-copied={copied ? "true" : "false"} aria-label={copied ? t("会话 ID 已复制") : t("复制会话 ID")} title={copied ? t("已复制") : t("复制会话 ID")} disabled={!sessionId} onClick={copySessionId}>
                        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                      </button>
                    </div>
                  </section>
                </div>
              )}

            </div>
          </div>

          {!embedded && !sessionWorkbench && <section className="drawer-preview" aria-label={t("体验预览")}>
            <div className="preview-heading">
              <div>

                <h3>{isAvatarMode ? t("数字人模式") : t("对话模式")}</h3>
              </div>
              <span className="preview-live-pill"><i />{t("配置预览")}</span>
            </div>

            <div className="experience-preview-card" data-mode={experienceMode}>
              {isAvatarMode ? (
                <>
                  {avatarDisplayConfig.renderPath === "hosted" && avatarPreviewImage ? <Image
                      className="experience-preview-image"
                      src={avatarPreviewImage}
                      alt={"" + (avatarDisplayName) + t(" 数字人配置预览")}
                      fill
                      priority
                      unoptimized={avatarPreviewImage.startsWith("blob:") || avatarPreviewImage.startsWith("data:") || avatarPreviewImage.startsWith("http")}
                      sizes="(max-width: 900px) 100vw, 60vw"
                    /> : avatarDisplayConfig.renderPath === "hosted" ? <div className="experience-preview-image" aria-label={t("当前形象暂无预览图片")} /> : selectedIdentityOnly && selectedOpenTalkingIdentity ? <Image
                      className="experience-preview-image"
                      src={selectedOpenTalkingIdentity.previewImageUrl}
                      alt={"" + (selectedOpenTalkingIdentity.name) + t(" 数字人形象配置预览")}
                      fill
                      priority
                      sizes="(max-width: 900px) 100vw, 60vw"
                    /> : open && selectedMotionPreviewUrl ? <MotionPreviewPlayer
                      previewUrl={selectedMotionPreviewUrl}
                      posterUrl={selectedOpenTalkingMotion?.previewImageUrl}
                      label={selectedMotionName}
                      autoPlay={!reducedMotion}
                    /> : <div className="avatar-motion-preview-empty"><Film /><strong>{t(selectedMotionName)}</strong><small>{t("当前分段式合成动作")}</small></div>}
                  <div className="experience-preview-vignette" />
                  <span className="avatar-preview-label">{avatarDisplayConfig.renderPath === "hosted" || selectedIdentityOnly ? <UserRound /> : <Film />}{avatarDisplayConfig.renderPath === "hosted" ? `${avatarDisplayName.toUpperCase()} · CONFIG PREVIEW` : selectedIdentityOnly ? `${selectedOpenTalkingIdentity?.name.toUpperCase()} · IDENTITY PREVIEW` : `${selectedMotionName.toUpperCase()} · ACTION PREVIEW`}</span>
                </>
              ) : <ExperienceModeDemo
                mode={experienceMode}
                avatarDisplayConfig={avatarDisplayConfig}
                avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
                compact
                active={open}
                reduceMotion={reducedMotion}
                voiceVisualTheme={voiceVisualTheme}
              />}
              {isAvatarMode && <div className="preview-call-state">
                <span><i />{avatarPreviewState}</span>
                <small>{t(avatarPreviewService)}</small>
              </div>}
            </div>

            <div className="preview-summary">
              <span><small>{t("模式")}</small><strong>{isAvatarMode ? avatarModeLabel : t("视觉对话")}</strong></span>
              <span><small>Persona</small><strong>{selectedPersonaLabel}</strong></span>
              {isAvatarMode && <span><small>{avatarDisplayConfig.renderPath === "hosted" || selectedIdentityOnly ? t("数字人形象") : t("数字人动作")}</small><strong>{avatarDisplayConfig.renderPath === "hosted" ? avatarDisplayName : selectedIdentityOnly ? selectedOpenTalkingIdentity?.name : selectedMotionName}</strong></span>}
              <span><small>{t("大模型")}</small><strong>{selectedModelLabel}</strong></span>
              <span><small>{t("音色")}</small><strong>{t(selectedVoiceLabel)}</strong></span>
              <span><small>{t("语音服务")}</small><strong>{ttsProvider === "doubao" ? t("火山 Seed TTS 2.0") : t("百炼 CosyVoice")}</strong></span>
            </div>

            <p className="preview-footnote">
              <span><Video aria-hidden="true" /></span>
              {isAvatarMode
                ? avatarDisplayConfig.renderPath === "hosted" && avatarDisplayConfig.provider === "anam"
                  ? t("实时托管形象已就绪；切换渲染模式时，分段式合成的动作选择会继续保留。")
                  : selectedIdentityOnly
                    ? t("已选择 OpenTalking 本地形象；当前仅进行口型对齐，不包含身体或镜头动作。")
                    : t("分段式动作选择已保存；新动作与人物配置统一在数字人工作台完成。")
                : t("对话模式使用视觉主题呈现语音状态，不加载数字人渲染服务。")}
            </p>
          </section>}
        </div>
        {pendingAvatarAssetDeletion && <AvatarAssetDeleteDialog
          asset={pendingAvatarAssetDeletion}
          onCancel={() => setPendingAvatarAssetDeletion(null)}
          onConfirm={confirmAvatarAssetDeletion}
        />}
      </aside>
    </>
  );
}

export function AvatarAssetDeleteDialog({ asset, onCancel, onConfirm }: {
  asset: PendingAvatarAssetDeletion;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useLanguage();
  const kindLabel = asset.kind === "identity" ? "数字人形象" : "数字人动作";
  return (
    <div className="avatar-asset-delete-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onCancel();
    }}>
      <section className="avatar-asset-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="avatar-asset-delete-title" aria-describedby="avatar-asset-delete-description">
        <span className="avatar-asset-delete-dialog-icon"><CircleAlert /></span>
        <div><h3 id="avatar-asset-delete-title">{t("删除")}{t(kindLabel)}？</h3></div>
        <p id="avatar-asset-delete-description"><strong>{<LocalizedText text={asset.label} />}</strong>{t("只会从这台设备的资产库移除，项目源文件和服务端记录不会被销毁。")}</p>
        <div className="avatar-asset-delete-dialog-actions">
          <button type="button" autoFocus onClick={onCancel}>{t("取消")}</button>
          <button type="button" data-danger="true" onClick={onConfirm}><Trash2 />{t("确认删除")}</button>
        </div>
      </section>
    </div>
  );
}

function MotionPreviewPlayer({
  previewUrl,
  posterUrl,
  label,
  autoPlay,
}: {
  previewUrl: string;
  posterUrl?: string;
  label: string;
  autoPlay: boolean;
}) {
  const { t } = useLanguage();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    setPlaying(false);
    if (!video) return;
    if (!autoPlay) {
      video.pause();
      return;
    }
    void video.play().catch(() => setPlaying(false));
  }, [autoPlay, previewUrl]);

  async function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    try {
      await video.play();
    } catch {
      setPlaying(false);
    }
  }

  return (
    <>
      <video
        ref={videoRef}
        className="experience-preview-video"
        src={previewUrl}
        poster={posterUrl}
        autoPlay={autoPlay}
        loop
        muted
        playsInline
        preload="metadata"
        aria-label={"" + (label) + t(" 动作预览")}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
      <button
        type="button"
        className="experience-preview-playback"
        data-playing={playing}
        aria-label={"" + (playing ? "暂停" : "播放") + t("动作预览：") + (label) + ""}
        onClick={() => void togglePlayback()}
      >
        {playing ? <Pause /> : <Play />}
        <span>{playing ? t("暂停动作") : t("播放动作")}</span>
      </button>
    </>
  );
}

function localizedTtsStatus(status: string) {
  if (status === "TTS configuration is not supported") return "当前运行中的语音服务不支持会话内切换；选择已保存为草稿";
  return status;
}
