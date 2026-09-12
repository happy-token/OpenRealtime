"use client";

import { useBottomVoiceStyle } from "@/hooks/use-bottom-voice-style";
import { BOTTOM_VOICE_STYLES, parseBottomVoiceStyle } from "@/lib/bottom-voice-style";
import styles from "./bottom-voice.module.css";

export function BottomVoiceStylePicker() {
  const { style, changeStyle, saveError } = useBottomVoiceStyle();
  return (
    <div className={styles.picker}>
      <label>
        <span>底部声音效果</span>
        <select aria-label="底部声音效果" value={style} onChange={(event) => changeStyle(parseBottomVoiceStyle(event.target.value))}>
          {BOTTOM_VOICE_STYLES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <small>贴窗口底边，随音量变化；无声时收成细线。</small>
      {saveError && <small role="status">{saveError}</small>}
    </div>
  );
}
