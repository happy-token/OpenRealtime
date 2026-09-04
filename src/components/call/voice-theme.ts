export const VOICE_VISUAL_THEMES = [
  "cloud",
  "liquid-glass",
  "aurora-particles",
  "radial",
  "circle",
  "bars",
  "debug",
] as const;

export type VoiceVisualTheme = (typeof VOICE_VISUAL_THEMES)[number];

export function isVoiceVisualTheme(value: string | null): value is VoiceVisualTheme {
  return VOICE_VISUAL_THEMES.some((theme) => theme === value);
}
