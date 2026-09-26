"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { CallView } from "@/components/call/call-view";
import { ConfirmationCard } from "@/components/call/confirmation-card";
import { BottomVoiceEdge } from "@/components/call/bottom-voice-edge";
import { SessionControlBar } from "@/components/call/session-control-bar";
import {
  CONNECTION_STATUS_LABELS,
  resolveSessionStatusLabel,
} from "@/components/call/session-copy";
import {
  freezeSessionTranscript,
  SessionEndedActions,
  type SessionReviewSnapshot,
} from "@/components/call/session-end-review";
import { SessionRecoveryNotice } from "@/components/call/session-recovery-notice";
import { SessionExperienceLayout } from "@/components/call/session-experience-layout";
import {
  enterPageForm,
  pageFormStorageKey,
  parsePageForm,
  restoreFromFullscreen,
  startPresentationSession,
  type PageForm,
  type PresentationSessionView,
} from "@/components/call/presentation-model";
import {
  ConfigDrawer,
  isConfigTab,
  type ConfigTab,
  type TtsRuntimeConfig,
} from "@/components/drawer/config-drawer";
import {
  DEFAULT_AVATAR_DISPLAY_CONFIG,
  parseAvatarDisplayConfig,
  parseExperienceMode,
  type AvatarDisplayConfig,
  type ExperienceMode,
} from "@/components/digital-human/types";
import {
  useVoiceSession,
} from "@/hooks/use-voice-session";
import { isVoiceVisualTheme, type VoiceVisualTheme } from "@/components/call/voice-theme";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  DEFAULT_TTS_VOICE,
  DIALECT_TTS_VOICE,
  TTS_CONFIG_STORAGE_KEY,
  isTtsDialect,
  isTtsVoice,
  type TtsDialect,
  type TtsProvider,
  type TtsVoice,
} from "@/components/drawer/voice-options";
import {
  AVATAR_DISPLAY_CONFIG_STORAGE_KEY,
  EXPERIENCE_MODE_STORAGE_KEY,
} from "@/lib/avatar-identity-sync";
import { avatarPersonaSelectionId } from "@/lib/avatar-persona";
import { readHostedAvatarProfile } from "@/lib/hosted-avatar-profile";
import { hostedAvatarRoleId } from "@/lib/hosted-avatar-role-id";
import { fetchTools } from "@/lib/tool-catalog-client";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import { loadCurrentAvatarCatalog } from "@/lib/avatar-library-catalog-client";
import {
  reconcileAvatarDisplayConfigWithOwnedAvatar,
} from "@/lib/avatar-session-config";
import { loadRequestedAvatarConfig } from "@/lib/requested-avatar-config";
import { useAppTheme } from "@/components/theme/app-theme-provider";
import { useProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import type { RolePresentationMode, RoleRecord } from "@/lib/role-records";
import { conversationHref } from "@/components/workspace/workspace-shell";
import { consumeRoleStartIntent } from "@/lib/role-start-intent";
import type { TranscriptEntry } from "@/voice/session/transcript";

const ChatView = dynamic(
  () => import("@/components/chat/chat-view").then((module) => module.ChatView),
  { ssr: false },
);

const VOICE_VISUAL_THEME_STORAGE_KEY = "voice-agent-visual-theme";
const REDUCED_MOTION_STORAGE_KEY = "voice-agent-reduced-motion";
const CAPTIONS_ENABLED_STORAGE_KEY = "voice-agent-captions-enabled";

export function OpenRealtimeApp({
  initialRole = null,
  initialRoleMode,
  officialAvatarId,
  initialToolNames = [],
  avatarArtifactPreviewEnabled = false,
  publicVoiceEnabled = false,
  defaultTtsProvider = "bailian",
}: {
  initialRole?: RoleRecord | null;
  initialRoleMode?: RolePresentationMode;
  officialAvatarId?: string;
  initialToolNames?: string[];
  avatarArtifactPreviewEnabled?: boolean;
  publicVoiceEnabled?: boolean;
  defaultTtsProvider?: TtsProvider;
}) {
  const router = useRouter();
  const engine = useVoiceSession({ publicVoiceEnabled });
  const ensureProviderKey = useProviderKeyGate();
  const { theme: appTheme, setTheme: setAppTheme } = useAppTheme();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitialTab, setDrawerInitialTab] = useState<ConfigTab>("display");
  const [sessionStarted, setSessionStarted] = useState(false);
  const [sessionPaused, setSessionPaused] = useState(false);
  const [avatarStarting, setAvatarStarting] = useState(false);
  const [presentationView, setPresentationView] = useState<PresentationSessionView | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [voiceVisualTheme, setVoiceVisualTheme] = useState<VoiceVisualTheme>("cloud");
  const [experienceMode, setExperienceMode] = useState<ExperienceMode>(
    officialAvatarId || (initialRoleMode && initialRoleMode !== "conversation") ? "avatar" : "voice",
  );
  const [selectedRoleMode, setSelectedRoleMode] = useState<RolePresentationMode>(initialRoleMode ?? "conversation");
  const roleModeRequestId = useRef(0);
  const [roleConfigLoading, setRoleConfigLoading] = useState(Boolean(officialAvatarId || (initialRole && initialRoleMode && initialRoleMode !== "conversation")));
  const [roleConfigReady, setRoleConfigReady] = useState(!officialAvatarId && (!initialRole || !initialRoleMode || initialRoleMode === "conversation"));
  const [avatarDisplayConfig, setAvatarDisplayConfig] = useState<AvatarDisplayConfig>(DEFAULT_AVATAR_DISPLAY_CONFIG);
  const [avatarAmbientColor, setAvatarAmbientColor] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [focusComposerRequest, setFocusComposerRequest] = useState(0);
  const [sessionReview, setSessionReview] = useState<SessionReviewSnapshot | null>(null);
  const historyId = useRef<string | null>(null);
  const historyWrites = useRef<Promise<void>>(Promise.resolve());
  const [ttsVoice, setTtsVoice] = useState<TtsVoice>(() => initialRole?.voice_id ?? (
    defaultTtsProvider === "bailian" ? BAILIAN_CLONED_VOICE_OPTIONS[0].value : DEFAULT_TTS_VOICE
  ));
  const [ttsProvider, setTtsProvider] = useState<TtsProvider>(initialRole?.voice_provider ?? defaultTtsProvider);
  const [ttsSpeechRate, setTtsSpeechRate] = useState(0);
  const [ttsDialect, setTtsDialect] = useState<TtsDialect>("");
  const configureTts = engine.configureTts;
  const configureAvatarPersona = engine.configureAvatarPersona;
  const configureTools = engine.configureTools;

  const connected = engine.connection === "open";

  const saveHistory = useCallback((entries: TranscriptEntry[], ended: boolean) => {
    const id = historyId.current;
    if (!id || !entries.some((entry) => entry.text.trim())) return;
    const mode = selectedRoleMode;
    historyWrites.current = historyWrites.current.catch(() => undefined).then(async () => {
      const body = JSON.stringify({ id, roleId: officialAvatarId ? hostedAvatarRoleId(officialAvatarId) : initialRole?.role_id ?? null,
        roleName: initialRole?.display_name ?? avatarDisplayConfig.hostedAvatarDisplayName ?? "默认助手", mode, entries, ended });
      const response = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: ended && body.length < 60_000,
        body,
      });
      if (!response.ok) throw new Error("保存对话记录失败");
      window.dispatchEvent(new Event("openrealtime:conversations-updated"));
    });
  }, [avatarDisplayConfig.hostedAvatarDisplayName, initialRole, officialAvatarId, selectedRoleMode]);

  useEffect(() => {
    if (!sessionStarted || sessionReview || !historyId.current || !engine.transcript.length) return;
    const timer = window.setTimeout(() => saveHistory(freezeSessionTranscript(engine.transcript), false), 800);
    return () => window.clearTimeout(timer);
  }, [engine.transcript, saveHistory, sessionReview, sessionStarted]);

  useEffect(() => {
    if (sessionReview) saveHistory(sessionReview.entries, true);
  }, [saveHistory, sessionReview]);

  const preferredPageForm = useCallback((mode: ExperienceMode): PageForm => (
    parsePageForm(window.localStorage.getItem(pageFormStorageKey(mode)))
  ), []);

  useEffect(() => {
    setAvatarAmbientColor(null);
  }, [experienceMode, avatarDisplayConfig]);

  const openSettings = useCallback((tab: ConfigTab = "display") => {
    setDrawerInitialTab(tab);
    setDrawerOpen(true);
  }, []);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem(VOICE_VISUAL_THEME_STORAGE_KEY);
    if (isVoiceVisualTheme(savedTheme)) setVoiceVisualTheme(savedTheme);
    const savedExperienceMode = window.localStorage.getItem(EXPERIENCE_MODE_STORAGE_KEY);
    const requestedExperienceMode: ExperienceMode = officialAvatarId || (initialRoleMode && initialRoleMode !== "conversation") ? "avatar" : "voice";
    setSelectedRoleMode(officialAvatarId ? "realtime" : initialRoleMode ?? initialRole?.default_mode ?? "conversation");
    setExperienceMode(officialAvatarId || initialRoleMode ? requestedExperienceMode : parseExperienceMode(savedExperienceMode));
    setReducedMotion(window.localStorage.getItem(REDUCED_MOTION_STORAGE_KEY) === "true");
    setCaptionsEnabled(window.localStorage.getItem(CAPTIONS_ENABLED_STORAGE_KEY) !== "false");
    let storedConfig = DEFAULT_AVATAR_DISPLAY_CONFIG;
    try {
      storedConfig = parseAvatarDisplayConfig(JSON.parse(
        window.localStorage.getItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY) ?? "null",
      ));
      setAvatarDisplayConfig(storedConfig);
    } catch {
      window.localStorage.removeItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY);
    }
    const controller = new AbortController();
    const query = new URLSearchParams(window.location.search);
    const requestedAvatarId = officialAvatarId || initialRoleMode === "conversation" ? "" : query.get("avatar_id") ?? initialRole?.avatar_id ?? "";
    const defaultSelection = initialRoleMode ? initialRole?.default_selections?.[initialRoleMode as "motion" | "offline" | "lip-sync"] : undefined;
    const requestedConfigTab = query.get("open_config") ?? "";
    if (officialAvatarId) {
      setRoleConfigLoading(true);
      setRoleConfigReady(false);
      void fetch("/api/anam/avatars", { cache: "no-store", signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) throw new Error("实时数字人暂不可用");
          const catalog = await response.json() as { avatars?: { id: string; displayName: string; imageUrl: string; origin: string }[] };
          const avatar = catalog.avatars?.find((item) => item.id === officialAvatarId && (item.origin === "official" || item.origin === "personal"));
          if (!avatar) throw new Error("所选实时数字人不可用");
          if (controller.signal.aborted) return;
          setAvatarDisplayConfig({ ...storedConfig, renderPath: "hosted", provider: "anam", avatarProfileId: avatar.id, hostedAvatarDisplayName: avatar.displayName, hostedAvatarImageUrl: avatar.imageUrl });
          setRoleConfigReady(true);
          setRoleConfigLoading(false);
          setExperienceMode("avatar");
        }).catch((error: unknown) => {
          if (!controller.signal.aborted) {
            setRoleConfigLoading(false);
            setMicError(error instanceof Error ? error.message : "所选官方实时数字人加载失败");
          }
        });
    } else if (requestedAvatarId) {
      setRoleConfigLoading(true);
      setRoleConfigReady(false);
      void loadRequestedAvatarConfig(
        requestedAvatarId, storedConfig, controller.signal,
        query.get("avatar_action_id") ?? defaultSelection?.action_id,
        initialRoleMode,
        query.get("talking_variant_id") ?? defaultSelection?.talking_variant_id,
      ).then((nextConfig) => {
        if (controller.signal.aborted) return;
        setAvatarDisplayConfig(nextConfig);
        setRoleConfigReady(true);
        setRoleConfigLoading(false);
        setExperienceMode("avatar");
        window.localStorage.setItem(EXPERIENCE_MODE_STORAGE_KEY, "avatar");
        window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(nextConfig));
        if (isConfigTab(requestedConfigTab)) openSettings(requestedConfigTab);
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setRoleConfigLoading(false);
          setRoleConfigReady(false);
          setMicError(error instanceof Error ? error.message : "所选数字人加载失败");
        }
      });
    } else {
      setRoleConfigLoading(false);
      setRoleConfigReady(true);
    }
    if (!officialAvatarId && !requestedAvatarId && storedConfig.renderPath === "segmented") {
      void Promise.all([
        fetchOwnedAvatar(storedConfig.segmentedAvatarId, controller.signal),
        loadCurrentAvatarCatalog(controller.signal, { includeHostedAvatars: false }).catch(() => []),
      ]).then(([storedAvatar, catalog]) => {
        if (!storedAvatar) return;
        const catalogActionIds = catalog
          .find((avatar) => avatar.avatarId === storedConfig.segmentedAvatarId)
          ?.actions.map((action) => action.avatarActionId) ?? [];
        const nextConfig = reconcileAvatarDisplayConfigWithOwnedAvatar(
          storedConfig,
          storedAvatar,
          catalogActionIds,
        );
        if (nextConfig === storedConfig) return;
        setAvatarDisplayConfig(nextConfig);
        window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(nextConfig));
      }).catch(() => undefined);
    }
    return () => controller.abort();
  }, [initialRole?.avatar_id, initialRole?.default_mode, initialRole?.default_selections, initialRole?.role_id, initialRoleMode, officialAvatarId, openSettings]);

  useEffect(() => {
    function syncAvatarDisplayConfig(event: StorageEvent) {
      if (sessionStarted || event.key !== AVATAR_DISPLAY_CONFIG_STORAGE_KEY || !event.newValue) return;
      try {
        setAvatarDisplayConfig(parseAvatarDisplayConfig(JSON.parse(event.newValue)));
      } catch {
        return;
      }
    }
    window.addEventListener("storage", syncAvatarDisplayConfig);
    return () => window.removeEventListener("storage", syncAvatarDisplayConfig);
  }, [sessionStarted]);

  useEffect(() => {
    window.localStorage.setItem(REDUCED_MOTION_STORAGE_KEY, String(reducedMotion));
  }, [reducedMotion]);

  useEffect(() => {
    window.localStorage.setItem(CAPTIONS_ENABLED_STORAGE_KEY, String(captionsEnabled));
  }, [captionsEnabled]);

  useEffect(() => {
    if (initialRole) {
      setTtsProvider(initialRole.voice_provider);
      setTtsVoice(initialRole.voice_id);
      setTtsDialect(initialRole.voice_dialect ?? "");
      configureTts(initialRole.voice_provider, initialRole.voice_id, 0, initialRole.voice_dialect ?? "");
      return;
    }
    try {
      const saved = JSON.parse(window.localStorage.getItem(TTS_CONFIG_STORAGE_KEY) ?? "null") as {
        provider?: unknown;
        voice?: unknown;
        speechRate?: unknown;
        dialect?: unknown;
      } | null;
      if (saved?.provider === "bailian" || saved?.provider === "doubao") setTtsProvider(saved.provider);
      if (saved && isTtsVoice(saved.voice)) setTtsVoice(saved.voice);
      if (saved && isTtsDialect(saved.dialect)) {
        setTtsDialect(saved.provider === "bailian" || saved.voice === DIALECT_TTS_VOICE ? saved.dialect : "");
      }
      if (
        saved &&
        typeof saved.speechRate === "number" &&
        saved.speechRate >= -50 &&
        saved.speechRate <= 100
      ) {
        setTtsSpeechRate(saved.speechRate);
      }
    } catch {
      window.localStorage.removeItem(TTS_CONFIG_STORAGE_KEY);
    }
  }, [configureTts, initialRole]);

  useEffect(() => {
    if (initialRole) return;
    const timer = window.setTimeout(() => {
      window.localStorage.setItem(
        TTS_CONFIG_STORAGE_KEY,
        JSON.stringify({ provider: ttsProvider, voice: ttsVoice, speechRate: ttsSpeechRate, dialect: ttsDialect }),
      );
    }, 180);
    return () => window.clearTimeout(timer);
  }, [initialRole, ttsDialect, ttsProvider, ttsSpeechRate, ttsVoice]);

  const handleTtsRuntimeConfigChange = useCallback((config: TtsRuntimeConfig) => {
    setTtsProvider(config.provider);
    setTtsVoice(config.voice);
    setTtsDialect(config.dialect);
    configureTts(
      config.provider,
      config.voice,
      config.speechRate,
      config.dialect,
    );
  }, [configureTts]);

  useEffect(() => {
    if (initialRole) {
      configureAvatarPersona(initialRole.avatar_id, initialRole.persona_id);
      return;
    }
    configureAvatarPersona(avatarPersonaSelectionId({
      renderPath: avatarDisplayConfig.renderPath,
      avatarProfileId: avatarDisplayConfig.avatarProfileId,
      segmentedAvatarId: avatarDisplayConfig.segmentedAvatarId,
    }));
  }, [
    avatarDisplayConfig.avatarProfileId,
    avatarDisplayConfig.renderPath,
    avatarDisplayConfig.segmentedAvatarId,
    configureAvatarPersona,
    initialRole,
  ]);

  useEffect(() => {
    configureTools(initialRole ? [...initialToolNames, "search_knowledge_base"] : initialToolNames, initialRole?.role_id);
  }, [configureTools, initialToolNames, initialRole]);

  useEffect(() => {
    if (!officialAvatarId || !avatarDisplayConfig.hostedAvatarDisplayName) return;
    const profile = readHostedAvatarProfile(officialAvatarId, avatarDisplayConfig.hostedAvatarDisplayName);
    setTtsProvider(profile.voiceProvider);
    setTtsVoice(profile.voiceId);
    setTtsDialect(profile.voiceDialect);
    configureTts(profile.voiceProvider, profile.voiceId, 0, profile.voiceDialect);
    configureAvatarPersona(officialAvatarId, profile.personaId);
    const controller = new AbortController();
    void Promise.all([
      fetchTools(controller.signal),
      fetch(`/api/hosted-avatar-settings/${encodeURIComponent(officialAvatarId)}`, { cache: "no-store", signal: controller.signal })
        .then((response) => response.ok ? response.json() as Promise<{ documentIds?: string[] }> : { documentIds: [] }),
    ]).then(([tools, settings]) => {
      if (!controller.signal.aborted) configureTools([
        ...tools.filter((tool) => profile.toolIds.includes(tool.tool_id) && tool.enabled && (tool.builtin || tool.endpoint)).map((tool) => tool.function_name),
        ...(settings.documentIds?.length ? ["search_knowledge_base"] : []),
      ], hostedAvatarRoleId(officialAvatarId));
    }).catch(() => undefined);
    return () => controller.abort();
  }, [avatarDisplayConfig.hostedAvatarDisplayName, configureAvatarPersona, configureTools, configureTts, officialAvatarId]);

  function handleTtsVoiceChange(voice: TtsVoice) {
    setTtsVoice(voice);
    if (voice !== DIALECT_TTS_VOICE) setTtsDialect("");
  }

  function handleTtsDialectChange(dialect: TtsDialect) {
    setTtsDialect(dialect);
    if (dialect) setTtsVoice(DIALECT_TTS_VOICE);
  }

  const beginSession = useCallback(async (mode: ExperienceMode = experienceMode) => {
    if (!connected && !publicVoiceEnabled) return false;
    historyId.current = crypto.randomUUID();
    setSessionReview(null);
    engine.clearConversationDisplay();
    setSessionStarted(true);
    setPresentationView(startPresentationSession(mode, preferredPageForm(mode)));
    try {
      await engine.start(ttsProvider);
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      const message = error instanceof Error ? error.message : String(error);
      setMicError(publicVoiceEnabled ? message : `麦克风错误：${message}`);
      setFocusComposerRequest((request) => request + 1);
    }
    return true;
  }, [engine, connected, experienceMode, preferredPageForm, publicVoiceEnabled, ttsProvider]);

  const startDigitalHumanSession = useCallback((config: AvatarDisplayConfig) => {
    historyId.current = crypto.randomUUID();
    setSessionReview(null);
    setAvatarDisplayConfig(config);
    engine.clearConversationDisplay();
    setPresentationView(startPresentationSession("avatar", preferredPageForm("avatar")));
    setSessionStarted(true);
    setAvatarStarting(true);
    setSessionPaused(false);
    setMicError(null);
  }, [engine, preferredPageForm]);

  const handleHomeStart = useCallback(async (requestedMode: ExperienceMode = experienceMode) => {
    if (requestedMode === "avatar") {
      if (!publicVoiceEnabled && avatarDisplayConfig.renderPath === "hosted" && avatarDisplayConfig.provider === "anam") {
        try {
          if (!await ensureProviderKey("anam")) return;
        } catch (error) {
          setMicError(error instanceof Error ? error.message : "无法检查 Anam API Key");
          return;
        }
      }
      let launchConfig = avatarDisplayConfig;
      if (launchConfig.renderPath === "segmented") {
        try {
          const currentAvatar = await fetchOwnedAvatar(launchConfig.segmentedAvatarId);
          if (currentAvatar) {
            launchConfig = reconcileAvatarDisplayConfigWithOwnedAvatar(launchConfig, currentAvatar);
          }
        } catch (error) {
          setMicError(`数字人配置校验失败：${error instanceof Error ? error.message : String(error)}`);
          return;
        }
      }
      if (launchConfig !== avatarDisplayConfig) {
        setAvatarDisplayConfig(launchConfig);
        window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(launchConfig));
      }
      startDigitalHumanSession(launchConfig);
      return;
    }
    await beginSession("voice");
  }, [avatarDisplayConfig, beginSession, ensureProviderKey, experienceMode, startDigitalHumanSession, publicVoiceEnabled]);

  useEffect(() => {
    if (officialAvatarId || !initialRole || roleConfigLoading || !roleConfigReady || sessionStarted) return;
    if (!consumeRoleStartIntent(initialRole.role_id)) return;
    void handleHomeStart(selectedRoleMode === "conversation" ? "voice" : "avatar");
  }, [handleHomeStart, initialRole, officialAvatarId, roleConfigLoading, roleConfigReady, selectedRoleMode, sessionStarted]);

  const retryMicrophone = useCallback(async () => {
    try {
      await engine.start(ttsProvider);
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      const message = error instanceof Error ? error.message : String(error);
      setMicError(publicVoiceEnabled ? message : `麦克风错误：${message}`);
    }
  }, [engine, ttsProvider, publicVoiceEnabled]);

  const useTextFallback = useCallback(() => {
    engine.stop();
    setSessionPaused(true);
    setFocusComposerRequest((request) => request + 1);
  }, [engine]);

  const toggleSessionPause = useCallback(async () => {
    if (sessionPaused) {
      await retryMicrophone();
      return;
    }
    engine.stop();
    setSessionPaused(true);
  }, [engine, retryMicrophone, sessionPaused]);

  const terminateSession = useCallback(() => {
    setSessionReview({
      endedAt: Date.now(),
      entries: freezeSessionTranscript(engine.transcript),
    });
    engine.terminate();
    setAvatarStarting(false);
    setSessionPaused(true);
    setDrawerOpen(false);
    setMicError(null);
  }, [engine]);

  const returnHomeFromReview = useCallback(() => {
    setSessionReview(null);
    setSessionStarted(false);
    setPresentationView(null);
    setSessionPaused(false);
    engine.clearConversationDisplay();
  }, [engine]);

  const continueFromReview = useCallback(async () => {
    if (!connected && !publicVoiceEnabled) return;
    setSessionReview(null);
    try {
      await engine.start(ttsProvider);
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      const message = error instanceof Error ? error.message : String(error);
      setMicError(publicVoiceEnabled ? message : `麦克风错误：${message}`);
      setFocusComposerRequest((request) => request + 1);
    }
  }, [connected, engine, ttsProvider, publicVoiceEnabled]);

  function handleVoiceVisualThemeChange(theme: VoiceVisualTheme) {
    setVoiceVisualTheme(theme);
    window.localStorage.setItem(VOICE_VISUAL_THEME_STORAGE_KEY, theme);
  }

  function handleExperienceModeChange(mode: ExperienceMode) {
    if (sessionStarted) return;
    setExperienceMode(mode);
    if (mode === "voice") setSelectedRoleMode("conversation");
    window.localStorage.setItem(EXPERIENCE_MODE_STORAGE_KEY, mode);
  }

  function handleHomeRoleSelect(role: RoleRecord) {
    if (sessionStarted || role.role_id === initialRole?.role_id) return;
    const selection = role.default_selections?.[role.default_mode as "motion" | "offline" | "lip-sync"];
    router.push(conversationHref(role, role.default_mode, selection?.action_id, selection?.talking_variant_id));
  }

  async function handleHomeRoleModeSelect(mode: RolePresentationMode, actionId?: string, talkingVariantId?: string) {
    if (sessionStarted || !initialRole?.enabled_modes.includes(mode)) return;
    const requestId = ++roleModeRequestId.current;
    setRoleConfigLoading(true);
    try {
      let config = avatarDisplayConfig;
      if (mode !== "conversation") {
        if (!initialRole.avatar_id) throw new Error("这个角色没有可用的数字人形象");
        config = await loadRequestedAvatarConfig(initialRole.avatar_id, avatarDisplayConfig, new AbortController().signal, actionId, mode, talkingVariantId);
        if (requestId !== roleModeRequestId.current) return;
        handleAvatarDisplayConfigChange(config);
      }
      setSelectedRoleMode(mode);
      setRoleConfigReady(true);
      handleExperienceModeChange(mode === "conversation" ? "voice" : "avatar");
      const href = conversationHref(initialRole, mode, mode === "conversation" || mode === "realtime" ? null : config.segmentedAvatarActionId,
        mode === "offline" ? config.motionTalkingVariantId : null);
      window.history.replaceState(window.history.state, "", href);
    } finally {
      if (requestId === roleModeRequestId.current) setRoleConfigLoading(false);
    }
  }

  function handleAvatarDisplayConfigChange(config: AvatarDisplayConfig) {
    if (sessionStarted) return;
    setAvatarDisplayConfig(config);
    window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(config));
  }

  function handlePageFormChange(pageForm: PageForm) {
    setPresentationView((current) => {
      if (!current) return current;
      const next = enterPageForm(current, pageForm);
      window.localStorage.setItem(pageFormStorageKey(current.mode), next.pageForm);
      return next;
    });
  }

  const handleRestoreFromFullscreen = useCallback(() => {
    setPresentationView((current) => {
      if (!current) return current;
      const next = restoreFromFullscreen(current);
      window.localStorage.setItem(pageFormStorageKey(current.mode), next.pageForm);
      return next;
    });
  }, []);

  const handleAvatarRendererReady = useCallback(async () => {
    if (!avatarStarting) return;
    try {
      await engine.start(ttsProvider);
      engine.clearConversationDisplay();
      window.localStorage.setItem(
        AVATAR_DISPLAY_CONFIG_STORAGE_KEY,
        JSON.stringify(avatarDisplayConfig),
      );
      setAvatarStarting(false);
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setAvatarStarting(false);
      setSessionPaused(true);
      const message = error instanceof Error ? error.message : String(error);
      setMicError(publicVoiceEnabled ? message : `麦克风错误：${message}`);
      setFocusComposerRequest((request) => request + 1);
    }
  }, [avatarDisplayConfig, avatarStarting, engine, ttsProvider, publicVoiceEnabled]);

  const cancelAvatarStartup = useCallback(() => {
    engine.terminate();
    setAvatarStarting(false);
    setSessionStarted(false);
    setPresentationView(null);
    setMicError(null);
  }, [engine]);

  const pageForm = presentationView?.pageForm ?? "fullscreen";

  useEffect(() => {
    function restoreLayout(event: KeyboardEvent) {
      if (event.key !== "Escape" || pageForm !== "fullscreen" || drawerOpen || engine.pendingConfirmation) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [role=dialog], [role=menu]")) return;
      handleRestoreFromFullscreen();
    }
    window.addEventListener("keydown", restoreLayout);
    return () => window.removeEventListener("keydown", restoreLayout);
  }, [drawerOpen, engine.pendingConfirmation, handleRestoreFromFullscreen, pageForm]);

  const statusLabel = resolveSessionStatusLabel({
    state: engine.state,
    microphoneMuted: sessionStarted && sessionPaused,
    ended: Boolean(sessionReview),
  });

  useEffect(() => {
    if (!publicVoiceEnabled || !sessionStarted || sessionReview
      || engine.connection !== "error" || !engine.sessionError) return;
    setSessionReview({ endedAt: Date.now(), entries: freezeSessionTranscript(engine.transcript) });
    setSessionPaused(true);
    setMicError(engine.sessionError);
  }, [publicVoiceEnabled, sessionStarted, sessionReview, engine.connection, engine.sessionError, engine.transcript]);

  return (
    <div
      className="app-shell"
      data-state={engine.state}
      data-session={sessionStarted ? "active" : "idle"}
      data-view="call"
      data-experience-mode={experienceMode}
      data-entry-stage={sessionStarted ? "session" : "home"}
      data-session-phase={sessionReview ? "ended" : "active"}
    >
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />
      <header className="topbar">
        <div className="topbar-left">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span className="brand-wordmark">OpenRealtime</span>
          </span>
          <span className="status-dot" data-state={engine.state}>
            {statusLabel}
          </span>
          <span className={`offline-hint ${connected ? "hidden" : ""}`} data-offline={connected ? "false" : "true"}>
            {connected ? "" : CONNECTION_STATUS_LABELS[engine.connection] ?? ""}
          </span>
          {engine.credentialSummary && <span role="status" style={{ fontSize: 12, opacity: .8 }}>{engine.credentialSummary}</span>}
          {engine.trialSecondsRemaining !== null && <span role="timer" style={{ fontSize: 12 }}>
            平台语音剩余 {Math.floor(engine.trialSecondsRemaining / 60)}:{String(engine.trialSecondsRemaining % 60).padStart(2, "0")}
          </span>}
        </div>
      </header>

      <main className="app-main">
        {experienceMode === "avatar" ? <CallView
          hidden={false}
          sessionStarted={false}
          homeSessionActive={sessionStarted}
          state={engine.state}
          statusLabel={statusLabel}
          level={engine.level}
          currentTurnText={engine.caption}
          error={micError}
          connected={connected || publicVoiceEnabled}
          onStartSession={handleHomeStart}
          role={officialAvatarId ? null : initialRole}
          officialRealtime={Boolean(officialAvatarId)}
          roleMode={selectedRoleMode}
          onRoleSelect={handleHomeRoleSelect}
          onRoleModeSelect={handleHomeRoleModeSelect}
          homeConfigLoading={roleConfigLoading}
          homeConfigReady={roleConfigReady}
          visualTheme={voiceVisualTheme}
          onVisualThemeChange={handleVoiceVisualThemeChange}
          experienceMode={experienceMode}
          onExperienceModeChange={handleExperienceModeChange}
          avatarDisplayConfig={avatarDisplayConfig}
          onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
          ttsProvider={ttsProvider}
          setAvatarAudioSink={engine.setAvatarAudioSink}
          reducedMotion={reducedMotion}
          captionsEnabled={captionsEnabled}
        /> : null}

        {sessionStarted ? (
          <SessionExperienceLayout
            pageForm={pageForm}
            ambientColor={experienceMode === "avatar" ? avatarAmbientColor : null}
            onEnterFullscreen={() => handlePageFormChange("fullscreen")}
            surface={<CallView
              hidden={false}
              sessionStarted
              runtimeOnly={experienceMode === "avatar"}
              state={engine.state}
              statusLabel={statusLabel}
              level={engine.level}
              currentTurnText={engine.caption}
              error={micError}
              connected={connected || publicVoiceEnabled}
              onStartSession={handleHomeStart}
              visualTheme={voiceVisualTheme}
              onVisualThemeChange={handleVoiceVisualThemeChange}
              experienceMode={experienceMode}
              onExperienceModeChange={handleExperienceModeChange}
              avatarDisplayConfig={avatarDisplayConfig}
              onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
              ttsProvider={ttsProvider}
              setAvatarAudioSink={engine.setAvatarAudioSink}
              reducedMotion={reducedMotion}
              captionsEnabled={captionsEnabled && pageForm !== "sidecar"}
              onAvatarRendererReady={handleAvatarRendererReady}
              onAvatarAmbientColorChange={setAvatarAmbientColor}
              publicVoiceEnabled={publicVoiceEnabled}
              onVoiceAdmission={engine.prepareAdmission}
              suspendRenderer={Boolean(sessionReview) && publicVoiceEnabled}
            />}
            surfaceOverlay={sessionReview ? <SessionEndedActions
              connected={connected || publicVoiceEnabled}
              pageForm={pageForm}
              onContinue={continueFromReview}
              onReturnHome={returnHomeFromReview}
            /> : null}
            conversation={<ChatView entries={sessionReview?.entries ?? engine.transcript} active={pageForm !== "fullscreen"} />}
            recovery={sessionReview ? null : <SessionRecoveryNotice
              connection={engine.connection}
              micError={micError}
              micAvailable={engine.micAvailable}
              sessionError={engine.sessionError}
              onRetryConnection={engine.retryConnection}
              onRetryMicrophone={retryMicrophone}
              onUseText={useTextFallback}
              voiceOnly={publicVoiceEnabled}
            />}
            controls={<SessionControlBar
              pageForm={pageForm}
              paused={sessionPaused}
              captionsEnabled={captionsEnabled}
              onPageFormChange={handlePageFormChange}
              onCaptionsChange={setCaptionsEnabled}
              onPauseToggle={toggleSessionPause}
              onOpenSettings={() => openSettings()}
              onTerminate={terminateSession}
              onSendText={engine.sendText}
              assistantBusy={engine.state === "thinking" || engine.state === "speaking"}
              onStopReply={engine.stopReply}
              focusComposerRequest={focusComposerRequest}
              ended={Boolean(sessionReview)}
            />}
          />
        ) : experienceMode === "voice" ? <CallView
          hidden={false}
          sessionStarted={false}
          state={engine.state}
          statusLabel={statusLabel}
          level={engine.level}
          currentTurnText={engine.caption}
          error={micError}
          connected={connected || publicVoiceEnabled}
          onStartSession={handleHomeStart}
          role={officialAvatarId ? null : initialRole}
          officialRealtime={Boolean(officialAvatarId)}
          roleMode={selectedRoleMode}
          onRoleSelect={handleHomeRoleSelect}
          onRoleModeSelect={handleHomeRoleModeSelect}
          homeConfigLoading={roleConfigLoading}
          homeConfigReady={roleConfigReady}
          visualTheme={voiceVisualTheme}
          onVisualThemeChange={handleVoiceVisualThemeChange}
          experienceMode={experienceMode}
          onExperienceModeChange={handleExperienceModeChange}
          avatarDisplayConfig={avatarDisplayConfig}
          onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
          ttsProvider={ttsProvider}
          setAvatarAudioSink={engine.setAvatarAudioSink}
          reducedMotion={reducedMotion}
          captionsEnabled={captionsEnabled}
        /> : null}
      </main>

      {sessionStarted && !sessionReview && !avatarStarting && (
        <BottomVoiceEdge state={engine.state} level={engine.level} muted={sessionPaused}
          connected={connected} reducedMotion={reducedMotion} />
      )}

      {engine.pendingConfirmation && (
        <div className="confirmation-overlay">
          <ConfirmationCard
            pending={engine.pendingConfirmation}
            onDecision={engine.resolveConfirmation}
          />
        </div>
      )}

      {sessionStarted && avatarStarting && (
        <button
          type="button"
          className="avatar-startup-return"
          aria-label="取消启动并返回主页"
          title="取消启动并返回主页"
          onClick={cancelAvatarStartup}
        >
          <ArrowLeft aria-hidden="true" />
        </button>
      )}

      {!sessionReview && (sessionStarted || drawerOpen) && <ConfigDrawer
        open={drawerOpen}
        variant={sessionStarted ? "session" : "drawer"}
        initialTab={drawerInitialTab}
        onClose={() => setDrawerOpen(false)}
        voiceVisualTheme={voiceVisualTheme}
        onVoiceVisualThemeChange={handleVoiceVisualThemeChange}
        ttsVoice={ttsVoice}
        ttsSpeechRate={ttsSpeechRate}
        ttsDialect={ttsDialect}
        ttsConfigurable={engine.ttsConfigurable}
        ttsPreviewAvailable={engine.ttsPreviewAvailable}
        publicVoiceEnabled={publicVoiceEnabled}
        ttsConfigStatus={engine.ttsConfigStatus}
        onTtsVoiceChange={handleTtsVoiceChange}
        onTtsRuntimeConfigChange={handleTtsRuntimeConfigChange}
        onTtsSpeechRateChange={setTtsSpeechRate}
        onTtsDialectChange={handleTtsDialectChange}
        experienceMode={experienceMode}
        onExperienceModeChange={handleExperienceModeChange}
        avatarDisplayConfig={avatarDisplayConfig}
        onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
        avatarConfigLocked={sessionStarted}
        avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
        reducedMotion={reducedMotion}
        onReducedMotionChange={setReducedMotion}
        appTheme={appTheme}
        onAppThemeChange={setAppTheme}
        setBargeInMuted={engine.setBargeInMuted}
        setNoiseSuppression={engine.setNoiseSuppression}
        setVolume={engine.setVolume}
        sessionId={engine.sessionId}
      />}
    </div>
  );
}
