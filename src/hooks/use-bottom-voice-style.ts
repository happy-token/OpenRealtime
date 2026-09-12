"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BOTTOM_VOICE_STORAGE_KEY, BOTTOM_VOICE_STYLE_EVENT, DEFAULT_BOTTOM_VOICE_STYLE,
  parseBottomVoiceStyle, type BottomVoiceStyle,
} from "@/lib/bottom-voice-style";

export function useBottomVoiceStyle() {
  const [style, setStyle] = useState<BottomVoiceStyle>(DEFAULT_BOTTOM_VOICE_STYLE);
  const [saveError, setSaveError] = useState<string | null>(null);
  useEffect(() => {
    function readStored() {
      try { setStyle(parseBottomVoiceStyle(window.localStorage.getItem(BOTTOM_VOICE_STORAGE_KEY))); }
      catch { /* Storage may be disabled; the default remains usable. */ }
    }
    function onStorage(event: StorageEvent) {
      if (event.key === BOTTOM_VOICE_STORAGE_KEY || event.key === null) readStored();
    }
    function onChange(event: Event) {
      setStyle(parseBottomVoiceStyle((event as CustomEvent<BottomVoiceStyle>).detail));
    }
    readStored();
    window.addEventListener("storage", onStorage);
    window.addEventListener(BOTTOM_VOICE_STYLE_EVENT, onChange);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(BOTTOM_VOICE_STYLE_EVENT, onChange);
    };
  }, []);
  const changeStyle = useCallback((next: BottomVoiceStyle) => {
    const normalized = parseBottomVoiceStyle(next);
    setStyle(normalized);
    setSaveError(null);
    try { window.localStorage.setItem(BOTTOM_VOICE_STORAGE_KEY, normalized); }
    catch { setSaveError("已切换效果，但浏览器未允许保存，刷新后将恢复默认。"); }
    window.dispatchEvent(new CustomEvent(BOTTOM_VOICE_STYLE_EVENT, { detail: normalized }));
  }, []);
  return { style, changeStyle, saveError };
}
