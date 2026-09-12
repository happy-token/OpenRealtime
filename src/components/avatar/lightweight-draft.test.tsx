import { describe, expect, it } from "vitest";
import { matchingVariant, readLightweightDraft, selectIdle, type LightweightDraft } from "./lightweight-draft";

describe("lightweight source binding", () => {
  const draft: LightweightDraft = { idle: "idle-a", method: "minimax", variant: { sourceId: "idle-a", sourceUrl: "/a.mp4", videoUrl: "/api/ltx/image-to-video/task/result", method: "minimax" } };
  it("discards legacy arbitrary talking selections", () => {
    expect(readLightweightDraft({ idle: "idle-a", talking: "unrelated" })).toEqual({ idle: "idle-a", method: "musetalk" });
  });
  it("invalidates a generated variant when the base changes", () => {
    expect(selectIdle(draft, "idle-b")).toEqual({ idle: "idle-b", method: "minimax" });
    expect(selectIdle(draft, "idle-a")).toBe(draft);
  });
  it("requires both source identity and video version to match", () => {
    expect(matchingVariant(draft, "/a.mp4")).toBe(draft.variant);
    expect(matchingVariant(draft, "/replacement.mp4")).toBeUndefined();
    expect(matchingVariant(draft, null)).toBeUndefined();
  });
  it("restores only validated local generation references", () => {
    expect(readLightweightDraft(draft)).toEqual(draft);
    expect(readLightweightDraft({ ...draft, variant: { ...draft.variant, sourceId: "other" } }).variant).toBeUndefined();
    expect(readLightweightDraft({ ...draft, variant: { ...draft.variant, videoUrl: "https://external.test/video" } }).variant).toBeUndefined();
  });
});
