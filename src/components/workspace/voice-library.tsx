"use client";
import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useState } from "react";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  TTS_CONFIG_STORAGE_KEY,
  isTtsDialect,
  isTtsVoice,
} from "@/components/drawer/voice-options";
import { VoiceSelector, type VoiceSelection } from "@/components/voice/voice-selector";
import styles from "./resource-library-screen.module.css";

const DEFAULT_SELECTION: VoiceSelection = {
  provider: "bailian",
  voice: BAILIAN_CLONED_VOICE_OPTIONS[0].value,
  dialect: "",
};

export function VoiceLibrary() {
  const { t } = useLanguage();
  const [selection, setSelection] = useState<VoiceSelection>(DEFAULT_SELECTION);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(TTS_CONFIG_STORAGE_KEY) ?? "null") as Partial<VoiceSelection> | null;
      if (saved && (saved.provider === "bailian" || saved.provider === "doubao") && isTtsVoice(saved.voice) && isTtsDialect(saved.dialect ?? "")) {
        setSelection({ provider: saved.provider, voice: saved.voice, dialect: saved.dialect ?? "" });
      }
    } catch { /* Keep the safe default when stored settings are invalid. */ }
  }, []);

  function choose(next: VoiceSelection) {
    setSelection(next);
    let speechRate = 0;
    try {
      const saved = JSON.parse(window.localStorage.getItem(TTS_CONFIG_STORAGE_KEY) ?? "null") as { speechRate?: unknown } | null;
      if (typeof saved?.speechRate === "number" && saved.speechRate >= -50 && saved.speechRate <= 100) speechRate = saved.speechRate;
    } catch { /* Replace invalid saved settings. */ }
    window.localStorage.setItem(TTS_CONFIG_STORAGE_KEY, JSON.stringify({ ...next, speechRate }));
  }

  return <div className={styles.libraryView}>
    <div className={styles.libraryHeading}>
      <div><h2>{t("声音")}</h2><p>{t("选择对话默认声音；供应商、克隆、官方音色和方言与角色配置共用同一套能力。")}</p></div>
    </div>
    <div className={styles.sharedVoiceSelector}>
      <VoiceSelector value={selection} onChange={choose} allowClone allowManagement currentLabel={t("当前对话默认声音")} />
    </div>
  </div>;
}
