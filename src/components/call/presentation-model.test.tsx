import { describe, expect, it } from "vitest";
import {
  enterPageForm,
  PRESENTATION_MODE_OPTIONS,
  startPresentationSession,
  parsePresentationMode,
  restoreFromFullscreen,
} from "./presentation-model";

describe("presentation model", () => {
  it("migrates the former chat mode into the conversation presentation", () => {
    expect(parsePresentationMode("chat")).toBe("voice");
    expect(PRESENTATION_MODE_OPTIONS.map((option) => option.id)).toEqual(["voice", "avatar"]);
  });

  it("returns fullscreen to its source or content when the session started fullscreen", () => {
    const initial = startPresentationSession("voice");
    expect(restoreFromFullscreen(initial).pageForm).toBe("content");

    const sidecar = enterPageForm(initial, "sidecar");
    const enlarged = enterPageForm(sidecar, "fullscreen");
    expect(restoreFromFullscreen(enlarged).pageForm).toBe("sidecar");
  });
});
