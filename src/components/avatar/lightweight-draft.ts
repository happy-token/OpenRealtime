export type TalkingMethod = "wav2lip" | "minimax" | "musetalk" | "lipforcing";
export type LightweightDraft = {
  idle: string;
  method: TalkingMethod;
  variant?: { sourceId: string; sourceUrl: string; videoUrl: string; method: TalkingMethod };
};
export function readLightweightDraft(raw: unknown): LightweightDraft {
  const empty: LightweightDraft = { idle: "", method: "musetalk" };
  if (!raw || typeof raw !== "object") return empty;
  const record = raw as Record<string, unknown>;
  // Legacy independent talking selections have no provenance and cannot be reused.
  const draft: LightweightDraft = { idle: typeof record.idle === "string" ? record.idle : "", method: record.method === "wav2lip" || record.method === "minimax" || record.method === "lipforcing" ? record.method : "musetalk" };
  const variant = record.variant as Record<string, unknown> | undefined;
  if (variant && typeof variant === "object" && variant.sourceId === draft.idle
    && typeof variant.sourceUrl === "string" && typeof variant.videoUrl === "string"
    && /^\/api\/ltx\/image-to-video\/[^/]+\/result$/.test(variant.videoUrl)
    && variant.method === "minimax") {
    draft.variant = { sourceId: draft.idle, sourceUrl: variant.sourceUrl, videoUrl: variant.videoUrl, method: variant.method };
  }
  return draft;
}
export function selectIdle(draft: LightweightDraft, idle: string): LightweightDraft {
  return idle === draft.idle ? draft : { idle, method: draft.method };
}
export function matchingVariant(draft: LightweightDraft, sourceUrl?: string | null) {
  return draft.variant?.sourceId === draft.idle && draft.variant.sourceUrl === sourceUrl ? draft.variant : undefined;
}
