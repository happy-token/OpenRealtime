"use client";

import { useEffect, useRef, useState } from "react";
import type { ConversationState } from "@/hooks/use-voice-session";
import { getLiquidGlassOrbParams } from "./liquid-glass-orb-params";
import { createLiquidGlassOrbRenderer } from "./liquid-glass-orb-renderer";

interface LiquidGlassOrbProps {
  state: ConversationState;
  level: number;
}

export function LiquidGlassOrb({ state, level }: LiquidGlassOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const paramsRef = useRef(getLiquidGlassOrbParams(state, level));
  const [renderState, setRenderState] = useState<"loading" | "ready" | "fallback">("loading");
  paramsRef.current = getLiquidGlassOrbParams(state, level);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    return createLiquidGlassOrbRenderer({
      canvas,
      getParams: () => paramsRef.current,
      onReady: () => setRenderState("ready"),
      onError: () => setRenderState("fallback"),
    });
  }, []);

  return (
    <div className="liquid-glass-orb" data-render-state={renderState} aria-hidden="true">
      <span className="liquid-glass-orb-fallback" />
      <canvas ref={canvasRef} className="liquid-glass-orb-canvas" />
    </div>
  );
}
