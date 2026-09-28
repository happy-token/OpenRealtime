"use client";
import { SelectMenu } from "@/components/ui/select-menu";

import { useBottomVoiceStyle } from "@/hooks/use-bottom-voice-style";
import { BOTTOM_VOICE_STYLES, parseBottomVoiceStyle } from "@/lib/bottom-voice-style";
import styles from "./bottom-voice.module.css";

export function BottomVoiceStylePicker() {
  const { style, changeStyle, saveError } = useBottomVoiceStyle();
  return (
    <div className={styles.picker}>
      <label>
        <span>底部声音效果</span>
        <SelectMenu fullWidth value={String(style)} ariaLabel="底部声音效果" options={[...(BOTTOM_VOICE_STYLES.map((option) => ({ value: String(option.value), label: String(option.label) })))]} onChange={value => changeStyle(parseBottomVoiceStyle(value))} />
      </label>
      <small>贴窗口底边，随音量变化；无声时收成细线。</small>
      {saveError && <small role="status">{saveError}</small>}
    </div>
  );
}
