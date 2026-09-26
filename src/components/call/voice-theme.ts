export const VOICE_VISUAL_THEME_OPTIONS = [
  { id: "liquid-glass", name: "液态玻璃", note: "清透、柔和", colors: ["#f4f7ff", "#8a9cff", "#5de2ff"] },
  { id: "aurora-particles", name: "极光粒子", note: "灵动、有生命力", colors: ["#6bf0d0", "#7567ff", "#d06eff"] },
  { id: "cloud", name: "云雾", note: "自然、安静", colors: ["#ffffff", "#b8c6ff", "#7e8fe6"] },
  { id: "radial", name: "径向脉冲", note: "清晰、有节奏", colors: ["#87e9ff", "#6776ff", "#293164"] },
  { id: "circle", name: "柔和圆形", note: "克制、专注", colors: ["#f4f1ff", "#9fa8ff", "#5969cf"] },
  { id: "bars", name: "音频柱", note: "直观、实时", colors: ["#b7f5ff", "#61a9ff", "#4a52bd"] },
  { id: "debug", name: "调试面板", note: "状态与音量", colors: ["#d8ffe9", "#50c990", "#176052"] },
] as const;

export type VoiceVisualTheme = (typeof VOICE_VISUAL_THEME_OPTIONS)[number]["id"];
export const VOICE_VISUAL_THEMES: readonly VoiceVisualTheme[] = VOICE_VISUAL_THEME_OPTIONS.map((option) => option.id);

export function isVoiceVisualTheme(value: string | null): value is VoiceVisualTheme {
  return VOICE_VISUAL_THEMES.some((theme) => theme === value);
}
