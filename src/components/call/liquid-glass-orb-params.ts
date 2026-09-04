import type { ConversationState } from "@/hooks/use-voice-session";

export interface LiquidGlassOrbParams {
  style: "siri";
  glassEnabled: boolean;
  speed: number;
  radius: number;
  contourDeform: number;
  bandDensity: number;
  chromaticShift: number;
  metalScale: number;
  metalStretch: number;
  metalAngle: number;
  metalOffset: number;
  metalPhase: number;
  metalEvolution: number;
  metalRoughness: number;
  metalDepth: number;
  zoom: number;
  warp: number;
  ridgeAmt: number;
  sharp: number;
  shade: number;
  sheen: number;
  gloss: number;
  glassOpacity: number;
  shellMidAlpha: number;
  shellEdgeAlpha: number;
  exposure: number;
  edgeSoftness: number;
  edgeGlow: number;
  colorA: string;
  colorB: string;
  colorC: string;
  colorD: string;
  highlightColor: string;
  shellInner: string;
  shellMid: string;
  shellEdge: string;
  sheenColor: string;
  specColor: string;
  canvasColor: string;
  glowColor: string;
}

const SIRI_PRESET: LiquidGlassOrbParams = {
  style: "siri",
  glassEnabled: true,
  speed: 0.82,
  radius: 0.72,
  contourDeform: 0,
  bandDensity: 2,
  chromaticShift: 0.42,
  metalScale: 0.77,
  metalStretch: 0.23,
  metalAngle: 65,
  metalOffset: 0,
  metalPhase: 0,
  metalEvolution: 1,
  metalRoughness: 0.22,
  metalDepth: 0.25,
  zoom: 0.36,
  warp: 3.2,
  ridgeAmt: 0.5,
  sharp: 2.2,
  shade: 0.12,
  sheen: 0.28,
  gloss: 0.24,
  glassOpacity: 0.44,
  shellMidAlpha: 0.18,
  shellEdgeAlpha: 0.18,
  exposure: 2,
  edgeSoftness: 0.005,
  edgeGlow: 0,
  colorA: "#FFD86B",
  colorB: "#82F4FF",
  colorC: "#FF7BD5",
  colorD: "#8E6CFF",
  highlightColor: "#FFFFFF",
  shellInner: "#FFFFFF",
  shellMid: "#9BF4FF",
  shellEdge: "#C5A9FF",
  sheenColor: "#EAF4FF",
  specColor: "#DCEAFF",
  canvasColor: "#030409",
  glowColor: "#956CFF",
};

const STATE_SPEED: Record<ConversationState, number> = {
  idle: 0.36,
  listening: 0.68,
  thinking: 1.34,
  speaking: 0.92,
};

export function getLiquidGlassOrbParams(
  state: ConversationState,
  level: number,
): LiquidGlassOrbParams {
  const normalizedLevel = Math.min(1, Math.max(0, level));

  return {
    ...SIRI_PRESET,
    speed: STATE_SPEED[state] + normalizedLevel * (state === "speaking" ? 1.2 : 0.42),
    radius: SIRI_PRESET.radius + normalizedLevel * 0.025,
    contourDeform: state === "thinking" ? 0.08 : normalizedLevel * 0.06,
    edgeGlow: 0.04 + normalizedLevel * 0.18,
    exposure: SIRI_PRESET.exposure + normalizedLevel * 0.22,
  };
}
