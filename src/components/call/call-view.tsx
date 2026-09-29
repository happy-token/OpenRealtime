
import { LocalizedText } from "@/components/language/language-provider";
import type { ConversationState } from "@/hooks/use-voice-session";
import type { VoiceVisualTheme } from "./voice-theme";
import { DigitalHumanStage } from "@/components/digital-human/digital-human-stage";
import type { AvatarDisplayConfig, ExperienceMode } from "@/components/digital-human/types";
import type { AvatarAudioSink } from "@/voice/audio/avatar-output";
import type { TtsProvider } from "@/components/drawer/voice-options";
import type { VoiceAdmission } from "@/lib/voice-admission";
import type { RolePresentationMode, RoleRecord } from "@/lib/role-records";
import { HomePreviewWorkspace } from "./home-preview-workspace";
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
  role?: RoleRecord | null;
  officialRealtime?: boolean;
  roleMode?: RolePresentationMode;
  onRoleSelect?: (role: RoleRecord) => void;
  onRoleModeSelect?: (mode: RolePresentationMode, actionId?: string, talkingVariantId?: string) => Promise<void>;
  homeConfigLoading?: boolean;
  homeConfigReady?: boolean;
  visualTheme: VoiceVisualTheme;
  onVisualThemeChange: (theme: VoiceVisualTheme) => void;
  experienceMode: ExperienceMode;
  onExperienceModeChange: (mode: ExperienceMode) => void;
  avatarDisplayConfig: AvatarDisplayConfig;
  onAvatarDisplayConfigChange: (config: AvatarDisplayConfig) => void;
  ttsProvider: TtsProvider;
  roleId?: string;
  setAvatarAudioSink: (sink: AvatarAudioSink | null) => void;
  reducedMotion: boolean;
  captionsEnabled?: boolean;
  onAvatarRendererReady?: () => void;
  onAvatarAmbientColorChange?: (color: string | null) => void;
  publicVoiceEnabled?: boolean;
  onVoiceAdmission?: (admission: VoiceAdmission | null) => void;
  suspendRenderer?: boolean;
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
  role,
  officialRealtime = false,
  roleMode,
  onRoleSelect,
  onRoleModeSelect,
  homeConfigLoading,
  homeConfigReady,
  visualTheme,
  onVisualThemeChange,
  experienceMode,
  onExperienceModeChange,
  avatarDisplayConfig,
  onAvatarDisplayConfigChange,
  ttsProvider,
  roleId,
  setAvatarAudioSink,
  reducedMotion,
  captionsEnabled = true,
  onAvatarRendererReady,
  onAvatarAmbientColorChange,
  publicVoiceEnabled = false,
  onVoiceAdmission,
  suspendRenderer = false,
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
      {sessionStarted && experienceMode === "avatar" && suspendRenderer ? (
        <div className="avatar-session-ended" role="status">{<LocalizedText text={"数字人会话已结束"} />}</div>
      ) : sessionStarted && experienceMode === "avatar" ? (
        <DigitalHumanStage
          state={state}
          statusLabel={statusLabel}
          currentTurnText={currentTurnText}
          displayConfig={avatarDisplayConfig}
          setAvatarAudioSink={setAvatarAudioSink}
          captionsEnabled={captionsEnabled}
          onRendererReady={onAvatarRendererReady}
          onAmbientColorChange={onAvatarAmbientColorChange}
          publicVoiceEnabled={publicVoiceEnabled}
          ttsProvider={ttsProvider}
          roleId={roleId}
          onVoiceAdmission={onVoiceAdmission}
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
          role={role}
          officialRealtime={officialRealtime}
          roleMode={roleMode}
          onRoleSelect={onRoleSelect}
          onRoleModeSelect={onRoleModeSelect}
          configLoading={homeConfigLoading}
          configReady={homeConfigReady}
          connected={connected}
          error={error}
          visualTheme={visualTheme}
          experienceMode={experienceMode}
          avatarDisplayConfig={avatarDisplayConfig}
          reducedMotion={reducedMotion}
          onVisualThemeChange={onVisualThemeChange}
          onExperienceModeChange={onExperienceModeChange}
          onAvatarDisplayConfigChange={onAvatarDisplayConfigChange}
          onStartSession={onStartSession}
        />
      )}
    </section>
  );
}
