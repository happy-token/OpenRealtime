import type { CSSProperties } from "react";
import type { ConversationState } from "@/hooks/use-voice-session";

interface AuroraParticleOrbProps {
  state: ConversationState;
  level: number;
}

const PARTICLES = Array.from({ length: 18 }, (_, index) => ({
  x: 12 + ((index * 37) % 76),
  y: 8 + ((index * 53) % 82),
  delay: -((index * 0.37) % 3.6),
  size: 1 + (index % 3),
}));

export function AuroraParticleOrb({ state, level }: AuroraParticleOrbProps) {
  const style = {
    "--aurora-level": Math.min(1, Math.max(0, level)).toFixed(3),
  } as CSSProperties;

  return (
    <div className="aurora-particle-orb" data-state={state} style={style} aria-hidden="true">
      <span className="aurora-orb-depth aurora-orb-depth-one" />
      <span className="aurora-orb-depth aurora-orb-depth-two" />
      <span className="aurora-orb-blob aurora-orb-blob-one" />
      <span className="aurora-orb-blob aurora-orb-blob-two" />
      <span className="aurora-orb-core" />
      <span className="aurora-orb-ring" />
      <span className="aurora-orb-particles">
        {PARTICLES.map((particle, index) => (
          <i
            key={index}
            style={{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              width: particle.size,
              height: particle.size,
              animationDelay: `${particle.delay}s`,
            }}
          />
        ))}
      </span>
    </div>
  );
}
