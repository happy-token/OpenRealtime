export type PresentationMode = "voice" | "avatar";
export type PageForm = "fullscreen" | "sidecar" | "content";

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

export function startPresentationSession(mode: PresentationMode): PresentationSessionView {
  return { mode, pageForm: "fullscreen", fullscreenReturn: null };
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
