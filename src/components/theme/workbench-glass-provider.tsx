"use client";

import { useEffect } from "react";
import {
  readWorkbenchVisualPreferences,
  WORKBENCH_VISUAL_PREFERENCES_EVENT,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";

/** Makes the appearance sliders available to every page, including modal portals. */
export function WorkbenchGlassProvider() {
  useEffect(() => {
    const sync = () => {
      const tokens = workbenchSurfaceTokens(readWorkbenchVisualPreferences());
      const root = document.documentElement.style;
      root.setProperty("--panel-surface-alpha", tokens.surfaceAlpha);
      root.setProperty("--panel-highlight-alpha", tokens.highlightAlpha);
      root.setProperty("--panel-soft-alpha", tokens.softAlpha);
      root.setProperty("--panel-blur", tokens.blur);
    };
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, sync);
    };
  }, []);
  return null;
}
