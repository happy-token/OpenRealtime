export interface WorkbenchVisualPreferences {
  transparency: number;
  glassBlur: number;
}

export const DEFAULT_WORKBENCH_VISUAL_PREFERENCES: WorkbenchVisualPreferences = {
  transparency: 70,
  glassBlur: 10,
};

export const WORKBENCH_VISUAL_PREFERENCES_EVENT = "openrealtime:workbench-visual-preferences";

const TRANSPARENCY_STORAGE_KEY = "openrealtime-workbench-transparency";
const GLASS_BLUR_STORAGE_KEY = "openrealtime-workbench-glass-blur";

export function normalizeWorkbenchVisualPreferences(
  transparency: unknown,
  glassBlur: unknown,
): WorkbenchVisualPreferences {
  const parsedTransparency = transparency === null || transparency === "" ? Number.NaN : Number(transparency);
  const parsedGlassBlur = glassBlur === null || glassBlur === "" ? Number.NaN : Number(glassBlur);
  return {
    transparency: Number.isFinite(parsedTransparency) && parsedTransparency >= 12 && parsedTransparency <= 88
      ? parsedTransparency
      : DEFAULT_WORKBENCH_VISUAL_PREFERENCES.transparency,
    glassBlur: Number.isFinite(parsedGlassBlur) && parsedGlassBlur >= 0 && parsedGlassBlur <= 100
      ? parsedGlassBlur
      : DEFAULT_WORKBENCH_VISUAL_PREFERENCES.glassBlur,
  };
}

export function readWorkbenchVisualPreferences(): WorkbenchVisualPreferences {
  if (typeof window === "undefined") return DEFAULT_WORKBENCH_VISUAL_PREFERENCES;
  return normalizeWorkbenchVisualPreferences(
    window.localStorage.getItem(TRANSPARENCY_STORAGE_KEY),
    window.localStorage.getItem(GLASS_BLUR_STORAGE_KEY),
  );
}

export function writeWorkbenchVisualPreferences(preferences: WorkbenchVisualPreferences) {
  if (typeof window === "undefined") return;
  const normalized = normalizeWorkbenchVisualPreferences(preferences.transparency, preferences.glassBlur);
  window.localStorage.setItem(TRANSPARENCY_STORAGE_KEY, String(normalized.transparency));
  window.localStorage.setItem(GLASS_BLUR_STORAGE_KEY, String(normalized.glassBlur));
  window.dispatchEvent(new CustomEvent(WORKBENCH_VISUAL_PREFERENCES_EVENT, { detail: normalized }));
}

export function workbenchSurfaceTokens({ transparency, glassBlur }: WorkbenchVisualPreferences) {
  const surfaceAlpha = Math.max(.12, (100 - transparency) / 100);
  return {
    surfaceAlpha: surfaceAlpha.toFixed(2),
    highlightAlpha: Math.max(.025, surfaceAlpha * .24).toFixed(3),
    softAlpha: Math.max(.018, surfaceAlpha * .1).toFixed(3),
    blur: `${Math.round(glassBlur * .34)}px`,
  };
}
