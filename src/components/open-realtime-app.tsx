"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { CallView } from "@/components/call/call-view";
import type { AdvancedConfigTab } from "@/components/call/home-preview-workspace";
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
  DEFAULT_TTS_VOICE,
  DIALECT_TTS_VOICE,
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
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import { loadCurrentAvatarCatalog } from "@/lib/avatar-library-catalog-client";
import {
  reconcileAvatarDisplayConfigWithOwnedAvatar,
} from "@/lib/avatar-session-config";
import { loadRequestedAvatarConfig } from "@/lib/requested-avatar-config";
import { useAppTheme } from "@/components/theme/app-theme-provider";

const ChatView = dynamic(
  () => import("@/components/chat/chat-view").then((module) => module.ChatView),
  { ssr: false },
);

const VOICE_VISUAL_THEME_STORAGE_KEY = "voice-agent-visual-theme";
const TTS_CONFIG_STORAGE_KEY = "voice-agent-tts-config";
const REDUCED_MOTION_STORAGE_KEY = "voice-agent-reduced-motion";
const CAPTIONS_ENABLED_STORAGE_KEY = "voice-agent-captions-enabled";

export function OpenRealtimeApp({
  avatarArtifactPreviewEnabled = false,
}: {
  avatarArtifactPreviewEnabled?: boolean;
}) {
  const engine = useVoiceSession();
  const { theme: appTheme, setTheme: setAppTheme } = useAppTheme();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitialTab, setDrawerInitialTab] = useState<ConfigTab>("display");
  const [sessionStarted, setSessionStarted] = useState(false);
  const [sessionPaused, setSessionPaused] = useState(false);
  const [avatarStarting, setAvatarStarting] = useState(false);
  const [presentationView, setPresentationView] = useState<PresentationSessionView | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [voiceVisualTheme, setVoiceVisualTheme] = useState<VoiceVisualTheme>("cloud");
  const [experienceMode, setExperienceMode] = useState<ExperienceMode>("voice");
  const [avatarDisplayConfig, setAvatarDisplayConfig] = useState<AvatarDisplayConfig>(DEFAULT_AVATAR_DISPLAY_CONFIG);
  const [avatarAmbientColor, setAvatarAmbientColor] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [focusComposerRequest, setFocusComposerRequest] = useState(0);
  const [sessionReview, setSessionReview] = useState<SessionReviewSnapshot | null>(null);
  const [ttsVoice, setTtsVoice] = useState<TtsVoice>(DEFAULT_TTS_VOICE);
  const [ttsProvider, setTtsProvider] = useState<TtsProvider>("bailian");
  const [ttsSpeechRate, setTtsSpeechRate] = useState(0);
  const [ttsDialect, setTtsDialect] = useState<TtsDialect>("");
  const configureTts = engine.configureTts;
  const configureAvatarPersona = engine.configureAvatarPersona;

  const connected = engine.connection === "open";

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
    setExperienceMode(parseExperienceMode(savedExperienceMode));
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
    const requestedAvatarId = query.get("avatar_id") ?? "";
    const requestedConfigTab = query.get("open_config") ?? "";
    if (requestedAvatarId) {
      void loadRequestedAvatarConfig(
        requestedAvatarId, storedConfig, controller.signal,
        query.get("avatar_action_id") ?? undefined,
      ).then((nextConfig) => {
        if (controller.signal.aborted) return;
        setAvatarDisplayConfig(nextConfig);
        setExperienceMode("avatar");
        window.localStorage.setItem(EXPERIENCE_MODE_STORAGE_KEY, "avatar");
        window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(nextConfig));
        if (isConfigTab(requestedConfigTab)) openSettings(requestedConfigTab);
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMicError(error instanceof Error ? error.message : "所选数字人加载失败");
        }
      });
    } else if (storedConfig.renderPath === "segmented") {
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
  }, [openSettings]);

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
    try {
      const saved = JSON.parse(window.localStorage.getItem(TTS_CONFIG_STORAGE_KEY) ?? "null") as {
        voice?: unknown;
        speechRate?: unknown;
        dialect?: unknown;
      } | null;
      if (saved && isTtsVoice(saved.voice)) setTtsVoice(saved.voice);
      if (saved && isTtsDialect(saved.dialect)) {
        setTtsDialect(saved.voice === DIALECT_TTS_VOICE ? saved.dialect : "");
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
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      window.localStorage.setItem(
        TTS_CONFIG_STORAGE_KEY,
        JSON.stringify({ voice: ttsVoice, speechRate: ttsSpeechRate, dialect: ttsDialect }),
      );
    }, 180);
    return () => window.clearTimeout(timer);
  }, [ttsDialect, ttsSpeechRate, ttsVoice]);

  const handleTtsRuntimeConfigChange = useCallback((config: TtsRuntimeConfig) => {
    setTtsProvider(config.provider);
    configureTts(
      config.provider,
      config.voice,
      config.speechRate,
      config.dialect,
    );
  }, [configureTts]);

  useEffect(() => {
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
  ]);

  function handleTtsVoiceChange(voice: TtsVoice) {
    setTtsVoice(voice);
    if (voice !== DIALECT_TTS_VOICE) setTtsDialect("");
  }

  function handleTtsDialectChange(dialect: TtsDialect) {
    setTtsDialect(dialect);
    if (dialect) setTtsVoice(DIALECT_TTS_VOICE);
  }

  const beginSession = useCallback(async (mode: ExperienceMode = experienceMode) => {
    if (!connected) return false;
    setSessionReview(null);
    engine.clearConversationDisplay();
    setSessionStarted(true);
    setPresentationView(startPresentationSession(mode, preferredPageForm(mode)));
    try {
      await engine.start();
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      setMicError(`麦克风错误：${error instanceof Error ? error.message : String(error)}`);
      setFocusComposerRequest((request) => request + 1);
    }
    return true;
  }, [engine, connected, experienceMode, preferredPageForm]);

  const startDigitalHumanSession = useCallback((config: AvatarDisplayConfig) => {
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
  }, [avatarDisplayConfig, beginSession, experienceMode, startDigitalHumanSession]);

  const retryMicrophone = useCallback(async () => {
    try {
      await engine.start();
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      setMicError(`麦克风错误：${error instanceof Error ? error.message : String(error)}`);
    }
  }, [engine]);

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
    if (!connected) return;
    setSessionReview(null);
    try {
      await engine.start();
      setSessionPaused(false);
      setMicError(null);
    } catch (error) {
      setSessionPaused(true);
      setMicError(`麦克风错误：${error instanceof Error ? error.message : String(error)}`);
      setFocusComposerRequest((request) => request + 1);
    }
  }, [connected, engine]);

  function handleVoiceVisualThemeChange(theme: VoiceVisualTheme) {
    setVoiceVisualTheme(theme);
    window.localStorage.setItem(VOICE_VISUAL_THEME_STORAGE_KEY, theme);
  }

  function handleExperienceModeChange(mode: ExperienceMode) {
    if (sessionStarted) return;
    setExperienceMode(mode);
    window.localStorage.setItem(EXPERIENCE_MODE_STORAGE_KEY, mode);
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
      await engine.start();
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
      setMicError(`麦克风错误：${error instanceof Error ? error.message : String(error)}`);
      setFocusComposerRequest((request) => request + 1);
    }
  }, [avatarDisplayConfig, avatarStarting, engine]);

  const cancelAvatarStartup = useCallback(() => {
    engine.terminate();
    setAvatarStarting(false);
    setSessionStarted(false);
    setPresentationView(null);
    setMicError(null);
  }, [engine]);

  const pageForm = presentationView?.pageForm ?? "fullscreen";

  function renderHomeAdvancedSettings(
    tab: AdvancedConfigTab,
    onVoiceLabelChange: (label: string) => void,
    onModelLabelChange: (label: string) => void,
  ) {
    return <ConfigDrawer
      open
      initialTab={tab}
      variant="embedded"
      onClose={() => undefined}
      voiceVisualTheme={voiceVisualTheme}
      onVoiceVisualThemeChange={handleVoiceVisualThemeChange}
      ttsVoice={ttsVoice}
      ttsSpeechRate={ttsSpeechRate}
      ttsDialect={ttsDialect}
      ttsConfigurable={engine.ttsConfigurable}
      ttsPreviewAvailable={engine.ttsPreviewAvailable}
      ttsConfigStatus={engine.ttsConfigStatus}
      onTtsVoiceChange={handleTtsVoiceChange}
      onTtsRuntimeConfigChange={handleTtsRuntimeConfigChange}
      onSelectedVoiceLabelChange={onVoiceLabelChange}
      onSelectedModelLabelChange={onModelLabelChange}
      onTtsSpeechRateChange={setTtsSpeechRate}
      onTtsDialectChange={handleTtsDialectChange}
      experienceMode={experienceMode}
      onExperienceModeChange={handleExperienceModeChange}
      avatarDisplayConfig={avatarDisplayConfig}
      onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
      avatarConfigLocked={false}
      avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
      reducedMotion={reducedMotion}
      onReducedMotionChange={setReducedMotion}
      appTheme={appTheme}
      onAppThemeChange={setAppTheme}
      setBargeInMuted={engine.setBargeInMuted}
      setNoiseSuppression={engine.setNoiseSuppression}
      setVolume={engine.setVolume}
      sessionId={engine.sessionId}
    />;
  }

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
        </div>
        <Link className="documentation-link" href="/docs">文档</Link>
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
          connected={connected}
          onStartSession={handleHomeStart}
          visualTheme={voiceVisualTheme}
          onVisualThemeChange={handleVoiceVisualThemeChange}
          experienceMode={experienceMode}
          onExperienceModeChange={handleExperienceModeChange}
          avatarDisplayConfig={avatarDisplayConfig}
          onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
          ttsProvider={ttsProvider}
          ttsVoice={ttsVoice}
          settingsRequest={0}
          renderAdvancedSettings={renderHomeAdvancedSettings}
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
              connected={connected}
              onStartSession={handleHomeStart}
              visualTheme={voiceVisualTheme}
              onVisualThemeChange={handleVoiceVisualThemeChange}
              experienceMode={experienceMode}
              onExperienceModeChange={handleExperienceModeChange}
              avatarDisplayConfig={avatarDisplayConfig}
              onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
              ttsProvider={ttsProvider}
              ttsVoice={ttsVoice}
              settingsRequest={0}
              renderAdvancedSettings={renderHomeAdvancedSettings}
              setAvatarAudioSink={engine.setAvatarAudioSink}
              reducedMotion={reducedMotion}
              captionsEnabled={captionsEnabled && pageForm !== "sidecar"}
              onAvatarRendererReady={handleAvatarRendererReady}
              onAvatarAmbientColorChange={setAvatarAmbientColor}
            />}
            surfaceOverlay={sessionReview ? <SessionEndedActions
              connected={connected}
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
          connected={connected}
          onStartSession={handleHomeStart}
          visualTheme={voiceVisualTheme}
          onVisualThemeChange={handleVoiceVisualThemeChange}
          experienceMode={experienceMode}
          onExperienceModeChange={handleExperienceModeChange}
          avatarDisplayConfig={avatarDisplayConfig}
          onAvatarDisplayConfigChange={handleAvatarDisplayConfigChange}
          ttsProvider={ttsProvider}
          ttsVoice={ttsVoice}
          settingsRequest={0}
          renderAdvancedSettings={renderHomeAdvancedSettings}
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
