export type PresentationMode = "voice" | "avatar";
export type PageForm = "fullscreen" | "sidecar" | "content";

const PAGE_FORM_STORAGE_PREFIX = "openrealtime-session-page-form";

export interface PresentationSessionView {
  mode: PresentationMode;
  pageForm: PageForm;
  fullscreenReturn: Exclude<PageForm, "fullscreen"> | null;
}

export const PRESENTATION_MODE_OPTIONS = [
  { id: "voice", label: "对话模式", description: "视觉主题与实时声场" },
  { id: "avatar", label: "数字人模式", description: "人物形象、动作与口型" },
] as const satisfies ReadonlyArray<{
  id: PresentationMode;
  label: string;
  description: string;
}>;

export function parsePresentationMode(value: unknown): PresentationMode {
  return value === "avatar" ? "avatar" : "voice";
}

export function parsePageForm(value: unknown): PageForm {
  return value === "sidecar" || value === "content" ? value : "fullscreen";
}

export function pageFormStorageKey(mode: PresentationMode): string {
  return `${PAGE_FORM_STORAGE_PREFIX}-${mode}`;
}

export function startPresentationSession(
  mode: PresentationMode,
  pageForm: PageForm = "fullscreen",
): PresentationSessionView {
  return {
    mode,
    pageForm,
    fullscreenReturn: pageForm === "fullscreen" ? null : pageForm,
  };
}

export function enterPageForm(
  state: PresentationSessionView,
  pageForm: PageForm,
): PresentationSessionView {
  if (pageForm === "fullscreen") {
    return {
      ...state,
      pageForm,
      fullscreenReturn: state.pageForm === "fullscreen"
        ? state.fullscreenReturn
        : state.pageForm,
    };
  }
  return { ...state, pageForm, fullscreenReturn: pageForm };
}

export function restoreFromFullscreen(state: PresentationSessionView): PresentationSessionView {
  return enterPageForm(state, state.fullscreenReturn ?? "content");
}
