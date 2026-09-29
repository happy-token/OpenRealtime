export const APP_LANGUAGE_STORAGE_KEY = "openrealtime-language";
export type AppLanguage = "zh-CN" | "en";
export type LanguagePreference = "system" | AppLanguage;
export function isLanguagePreference(value: unknown): value is LanguagePreference {
  return value === "system" || value === "zh-CN" || value === "en";
}
export function resolveAppLanguage(preference: LanguagePreference, languages: readonly string[] = []): AppLanguage {
  if (preference !== "system") return preference;
  return languages[0]?.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}
