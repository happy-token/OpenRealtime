import type { CSSProperties } from "react";
import { Orb as OrbUi } from "orb-ui";
import type { ConversationState } from "@/hooks/use-voice-session";
import { AuroraParticleOrb } from "./aurora-particle-orb";
import { LiquidGlassOrb } from "./liquid-glass-orb";
import type { VoiceVisualTheme } from "./voice-theme";

interface OrbProps {
  state: ConversationState;
  level: number;
  theme: VoiceVisualTheme;
}

export function Orb({ state, level, theme }: OrbProps) {
  const style = { "--level": level.toFixed(3) } as CSSProperties;
  const normalizedLevel = Math.min(1, Math.max(0, level)).toFixed(3);

  if (theme === "liquid-glass") {
    return (
      <div
        className="orb orb-integration"
        data-orb-source="lersent001"
        data-state={state}
        data-level={normalizedLevel}
        style={style}
        role="img"
        aria-label="实时语音状态可视化"
      >
        <div className="orb-integration-aura" aria-hidden="true" />
        <div className="orb-integration-mount"><LiquidGlassOrb state={state} level={level} /></div>
      </div>
    );
  }

  if (theme === "aurora-particles") {
    return (
      <div
        className="orb orb-integration"
        data-orb-source="metasidd"
        data-state={state}
        data-level={normalizedLevel}
        style={style}
        role="img"
        aria-label="实时语音状态可视化"
      >
        <div className="orb-integration-aura" aria-hidden="true" />
        <div className="orb-integration-mount"><AuroraParticleOrb state={state} level={level} /></div>
      </div>
    );
  }

  // orb-ui intentionally hides the passive cloud in idle. Keep a calm,
  // zero-volume cloud visible while our external controls own the session.
  const visualState = theme === "cloud" && state === "idle" ? "listening" : state;

  return (
    <div className="orb orb-library" data-state={state} style={style} role="img" aria-label="实时语音状态可视化">
      <div className="orb-library-aura" aria-hidden="true" />
      <div className="orb-library-mount">
        <OrbUi
          theme={theme}
          state={visualState}
          volume={level}
          size={224}
          interactive={false}
          aria-label="实时语音状态可视化"
        />
      </div>
    </div>
  );
}
