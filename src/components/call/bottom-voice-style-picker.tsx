"use client";
import { useLanguage } from "@/components/language/language-provider";

import { SelectMenu } from "@/components/ui/select-menu";

import { useBottomVoiceStyle } from "@/hooks/use-bottom-voice-style";
import { BOTTOM_VOICE_STYLES, parseBottomVoiceStyle } from "@/lib/bottom-voice-style";
import styles from "./bottom-voice.module.css";

export function BottomVoiceStylePicker() {
  const { t } = useLanguage();
  const { style, changeStyle, saveError } = useBottomVoiceStyle();
  return (
    <div className={styles.picker}>
      <label>
        <span>{t("底部声音效果")}</span>
        <SelectMenu fullWidth value={String(style)} ariaLabel={t("底部声音效果")} options={[...(BOTTOM_VOICE_STYLES.map((option) => ({ value: String(option.value), label: String(option.label) })))]} onChange={value => changeStyle(parseBottomVoiceStyle(value))} />
      </label>
      <small>{t("贴窗口底边，随音量变化；无声时收成细线。")}</small>
      {saveError && <small role="status">{saveError}</small>}
    </div>
  );
}
