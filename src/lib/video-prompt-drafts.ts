import { VIDEO_PROMPT_STYLES } from "./ltx-avatar-action";
import type { AppLanguage } from "./app-language";
export type VideoPromptDrafts = Record<string, Partial<Record<AppLanguage, string>>>;
export function videoPromptDraftStorageKey(avatarId: string) { return `openrealtime:video-prompts:${avatarId}`; }
export function parseVideoPromptDrafts(raw: string | null): VideoPromptDrafts {
  if (!raw) return {};
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return {}; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: VideoPromptDrafts = {};
  for (const id of [...VIDEO_PROMPT_STYLES.map(style => style.id), "custom"]) {
    const candidate = (value as Record<string, unknown>)[id];
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    for (const language of ["zh-CN", "en"] as const) {
      const prompt = (candidate as Record<string, unknown>)[language];
      if (typeof prompt === "string" && prompt.length <= 5_000) result[id] = { ...result[id], [language]: prompt };
    }
  }
  return result;
}
