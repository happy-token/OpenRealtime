import type { ConversationState } from "@/hooks/use-voice-session";
import type { ReactNode } from "react";
import type { VoiceVisualTheme } from "./voice-theme";
import { DigitalHumanStage } from "@/components/digital-human/digital-human-stage";
import type { AvatarDisplayConfig, ExperienceMode } from "@/components/digital-human/types";
import type { AvatarAudioSink } from "@/voice/audio/avatar-output";
import type { TtsProvider, TtsVoice } from "@/components/drawer/voice-options";
import { HomePreviewWorkspace, type AdvancedConfigTab } from "./home-preview-workspace";
import { Orb } from "./orb";

interface CallViewProps {
  hidden: boolean;
  sessionStarted: boolean;
  homeSessionActive?: boolean;
  runtimeOnly?: boolean;
  state: ConversationState;
  statusLabel: string;
  level: number;
  currentTurnText: string;
  error: string | null;
  connected: boolean;
  onStartSession: (mode?: ExperienceMode) => void;
  visualTheme: VoiceVisualTheme;
  onVisualThemeChange: (theme: VoiceVisualTheme) => void;
  experienceMode: ExperienceMode;
  onExperienceModeChange: (mode: ExperienceMode) => void;
  avatarDisplayConfig: AvatarDisplayConfig;
  onAvatarDisplayConfigChange: (config: AvatarDisplayConfig) => void;
  ttsProvider: TtsProvider;
  ttsVoice: TtsVoice;
  settingsRequest: number;
  renderAdvancedSettings: (
    tab: AdvancedConfigTab,
    onVoiceLabelChange: (label: string) => void,
    onModelLabelChange: (label: string) => void,
  ) => ReactNode;
  setAvatarAudioSink: (sink: AvatarAudioSink | null) => void;
  reducedMotion: boolean;
  captionsEnabled?: boolean;
  onAvatarRendererReady?: () => void;
  onAvatarAmbientColorChange?: (color: string | null) => void;
}

export function CallView({
  hidden,
  sessionStarted,
  homeSessionActive = false,
  runtimeOnly = false,
  state,
  statusLabel,
  level,
  currentTurnText,
  error,
  connected,
  onStartSession,
  visualTheme,
  onVisualThemeChange,
  experienceMode,
  onExperienceModeChange,
  avatarDisplayConfig,
  onAvatarDisplayConfigChange,
  ttsProvider,
  ttsVoice,
  settingsRequest,
  renderAdvancedSettings,
  setAvatarAudioSink,
  reducedMotion,
  captionsEnabled = true,
  onAvatarRendererReady,
  onAvatarAmbientColorChange,
}: CallViewProps) {
  const statusPlacement = ["cloud", "liquid-glass", "aurora-particles", "radial", "circle"].includes(visualTheme)
    ? "center"
    : "below";

  return (
    <section
      className={`view call-view ${hidden ? "hidden" : ""}${runtimeOnly ? " avatar-runtime-only" : ""}`}
      data-session={sessionStarted ? "active" : "idle"}
      aria-hidden={hidden}
    >
      {sessionStarted && experienceMode === "avatar" ? (
        <DigitalHumanStage
          state={state}
          statusLabel={statusLabel}
          currentTurnText={currentTurnText}
          displayConfig={avatarDisplayConfig}
          setAvatarAudioSink={setAvatarAudioSink}
          captionsEnabled={captionsEnabled}
          onRendererReady={onAvatarRendererReady}
          onAmbientColorChange={onAvatarAmbientColorChange}
        />
      ) : sessionStarted ? (
        <div className="call-orb-wrap" data-state={state}>
          <div className="orb-motion-cluster">
            <div className="orb-status-stage">
              <Orb state={state} level={level} theme={visualTheme} />
              {statusPlacement === "center" && (
                <span className="orb-conversation-status orb-conversation-status-center" data-state={state} role="status" aria-live="polite" aria-atomic="true">
                  <i aria-hidden="true" />
                  {statusLabel}
                </span>
              )}
            </div>
            {statusPlacement === "below" && (
              <span className="orb-conversation-status orb-conversation-status-below" data-state={state} role="status" aria-live="polite" aria-atomic="true">
                <i aria-hidden="true" />
                {statusLabel}
              </span>
            )}
            {captionsEnabled && currentTurnText.trim() && (
              <p className="current-turn-text" data-state={state} aria-live="polite">
                {currentTurnText}
              </p>
            )}
          </div>
        </div>
      ) : (
        <HomePreviewWorkspace
          sessionActive={homeSessionActive}
          connected={connected}
          error={error}
          visualTheme={visualTheme}
          experienceMode={experienceMode}
          avatarDisplayConfig={avatarDisplayConfig}
          ttsProvider={ttsProvider}
          ttsVoice={ttsVoice}
          reducedMotion={reducedMotion}
          onVisualThemeChange={onVisualThemeChange}
          onExperienceModeChange={onExperienceModeChange}
          onAvatarDisplayConfigChange={onAvatarDisplayConfigChange}
          settingsRequest={settingsRequest}
          renderAdvancedSettings={renderAdvancedSettings}
          onStartSession={onStartSession}
        />
      )}
    </section>
  );
}
