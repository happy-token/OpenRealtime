export const BOTTOM_VOICE_STYLES = [
  { value: "ribbon", label: "A · 丝带光束" },
  { value: "aurora", label: "B · 柔和极光" },
  { value: "strings", label: "C · 极简弦线" },
  { value: "pulse", label: "D · 节奏脉冲" },
] as const;

export type BottomVoiceStyle = (typeof BOTTOM_VOICE_STYLES)[number]["value"];
export const DEFAULT_BOTTOM_VOICE_STYLE: BottomVoiceStyle = "aurora";
export const BOTTOM_VOICE_STORAGE_KEY = "openrealtime-bottom-voice-style";
export const BOTTOM_VOICE_STYLE_EVENT = "openrealtime:bottom-voice-style";

export function parseBottomVoiceStyle(value: unknown): BottomVoiceStyle {
  return BOTTOM_VOICE_STYLES.find((option) => option.value === value)?.value ?? DEFAULT_BOTTOM_VOICE_STYLE;
}

export function bottomVoiceLevel(state: string, level: number, muted: boolean, connected: boolean): number {
  if (!connected || (state !== "speaking" && (state !== "listening" || muted))) return 0;
  return Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0;
}
