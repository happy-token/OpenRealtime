export interface RecordingPreservationView {
  status: "preserved" | "unmarked" | "source-missing" | "unsupported" | "unavailable";
  marked_at: string | null;
  preserved_segments: number | null;
  pending_segments: number | null;
  unavailable_segments: number | null;
  storage_durable: boolean;
}
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
export function projectRecordingPreservation(value: unknown): RecordingPreservationView {
  if (!object(value) || typeof value.status !== "string" || !["preserved", "unmarked", "source-missing", "unsupported", "unavailable"].includes(value.status)
      || typeof value.storage_durable !== "boolean") throw new Error("invalid-preservation");
  if (value.status === "preserved" ?
    typeof value.marked_at !== "string" || !/T.+(?:Z|[+-]\d\d:\d\d)$/.test(value.marked_at) || !Number.isFinite(Date.parse(value.marked_at))
      || !count(value.preserved_segments) || !count(value.pending_segments) || !count(value.unavailable_segments)
    : value.marked_at !== null || value.preserved_segments !== null || value.pending_segments !== null || value.unavailable_segments !== null) throw new Error("invalid-preservation");
  return { status: value.status as RecordingPreservationView["status"], marked_at: value.marked_at as string | null,
    preserved_segments: value.preserved_segments as number | null, pending_segments: value.pending_segments as number | null,
    unavailable_segments: value.unavailable_segments as number | null, storage_durable: value.storage_durable };
}
export function projectPreservationResult(value: unknown, sessionId: string) {
  if (!object(value) || value.voice_session_id !== sessionId || value.preserved !== true
    || (value.status !== undefined && value.status !== "preserved")) throw new Error("invalid-preservation-result");
  const view = projectRecordingPreservation({ ...value, status: "preserved" });
  return { voice_session_id: sessionId, preserved: true as const, ...view };
}
