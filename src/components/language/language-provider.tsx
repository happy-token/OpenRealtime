"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { APP_LANGUAGE_STORAGE_KEY, isLanguagePreference, resolveAppLanguage, type AppLanguage, type LanguagePreference } from "@/lib/app-language";
import messages from "@/lib/i18n/en.json";

export function translate(text: string, language: AppLanguage, params?: Record<string, string>): string {
  const dictionary = messages as Record<string, string>;
  const lookup = (value: string) => Object.hasOwn(dictionary, value) ? dictionary[value] : value;
  let template = language === "en" ? lookup(text) : text;
  if (language === "en" && template === text && text.includes(" · ")) {
    const parts = text.split(" · ");
    if (parts.every(part => Object.hasOwn(dictionary, part) || !/[\u3400-\u9fff]/.test(part))) {
      template = parts.map(lookup).join(" · ");
    }
  }
  return template.replace(/\{(\w+)\}/g, (placeholder, key: string) => params?.[key] ?? placeholder);
}
const fallback = { language: "zh-CN" as AppLanguage, preference: "system" as LanguagePreference, setPreference: (value: LanguagePreference) => { void value; }, t: (text: string, params?: Record<string, string>) => translate(text, "zh-CN", params) };
const LanguageContext = createContext(fallback);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<LanguagePreference>("system");
  const [systemLanguages, setSystemLanguages] = useState<readonly string[]>(["zh-CN"]);
  const language = resolveAppLanguage(preference, systemLanguages);
  const setPreference = useCallback((next: LanguagePreference) => {
    setPreferenceState(next);
    try { localStorage.setItem(APP_LANGUAGE_STORAGE_KEY, next); } catch { /* Preference still applies in this tab when storage is unavailable. */ }
  }, []);
  useEffect(() => {
    const syncSystem = () => setSystemLanguages(navigator.languages.length ? navigator.languages : [navigator.language]);
    syncSystem();
    try {
      const saved = localStorage.getItem(APP_LANGUAGE_STORAGE_KEY);
      if (isLanguagePreference(saved)) setPreferenceState(saved);
    } catch { /* Follow the system when browser storage is unavailable. */ }
    const syncStorage = (event: StorageEvent) => {
      if (event.key === APP_LANGUAGE_STORAGE_KEY) setPreferenceState(isLanguagePreference(event.newValue) ? event.newValue : "system");
    };
    window.addEventListener("languagechange", syncSystem);
    window.addEventListener("storage", syncStorage);
    return () => { window.removeEventListener("languagechange", syncSystem); window.removeEventListener("storage", syncStorage); };
  }, []);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  useEffect(() => {
    let sourceTitle = document.title;
    let appliedTitle = sourceTitle;
    const localizeTitle = () => {
      if (document.title !== appliedTitle) sourceTitle = document.title;
      appliedTitle = translate(sourceTitle, language);
      if (document.title !== appliedTitle) document.title = appliedTitle;
    };
    localizeTitle();
    const observer = new MutationObserver(localizeTitle);
    observer.observe(document.querySelector("title") ?? document.head, { childList: true, characterData: true, subtree: true });
    return () => {
      observer.disconnect();
      if (document.title === appliedTitle) document.title = sourceTitle;
    };
  }, [language]);
  const value = useMemo(() => ({ language, preference, setPreference, t: (text: string, params?: Record<string, string>) => translate(text, language, params) }), [language, preference, setPreference]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() { return useContext(LanguageContext); }
export function LocalizedText({ text }: { text: ReactNode }) {
  const { t } = useLanguage();
  return typeof text === "string" ? t(text) : text;
}
