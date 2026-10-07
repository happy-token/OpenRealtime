import { isDiagnosticSessionId } from "./diagnostics-access";
import { projectRecordingPreservation, type RecordingPreservationView } from "./recording-preservation";

export const MAX_RECORDING_AUDIO_BYTES = 4 * 1024 * 1024 + 44;
export interface SessionRecordingRow {
  voice_session_id: string; artifact_id: string; item_id: string; journal_sequence: string;
  direction: "input" | "sent"; epoch: string; speech_id: string | null; stream_id: string;
  sample_rate_hz: number; channels: number; start_sample: number; sample_count: number;
  duration_ms: number; discontinuity: boolean; captured_at: string; retention_until: string;
  storage_durable: boolean; capture_boundary: "validated_input" | "transport_send_completed";
  playback_confirmation: "not-inferred"; generation: number; turn_id: string; response_id: string | null;
  size_bytes: number; sha256: string; status: "available" | "expired" | "deleted" | "unavailable";
  pinned: boolean; audio_url: string;
}
export interface SessionRecordingPage {
  voice_session_id: string; items: SessionRecordingRow[]; next_cursor: string | null;
  storage_status: "configured" | "not-configured";
  preservation?: RecordingPreservationView;
}
export function recordingSequence(value: unknown): value is string {
  return typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= BigInt("9223372036854775807");
}
const uint = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && Buffer.byteLength(v) <= 512;
const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
/** Server projection: never forward storage keys or provider URLs. */
export function projectRecordingPage(value: unknown, sessionId: string, after: string, limit: number): SessionRecordingPage {
  if (!object(value) || value.voice_session_id !== sessionId || !Array.isArray(value.items) || value.items.length > limit
    || typeof value.storage_status !== "string" || !["configured", "not-configured"].includes(value.storage_status)) throw new Error("invalid-page");
  let previous = BigInt(after);
  const keys = ["voice_session_id", "artifact_id", "item_id", "journal_sequence", "direction", "epoch", "speech_id", "stream_id", "sample_rate_hz", "channels", "start_sample", "sample_count", "duration_ms", "discontinuity", "captured_at", "retention_until", "storage_durable", "capture_boundary", "playback_confirmation", "generation", "turn_id", "response_id", "size_bytes", "sha256", "status", "pinned"];
  const items = value.items.map((r: unknown) => {
    if (!object(r) || r.voice_session_id !== sessionId || typeof r.artifact_id !== "string" || !isDiagnosticSessionId(r.artifact_id)
      || !text(r.item_id) || !recordingSequence(r.journal_sequence) || BigInt(r.journal_sequence) <= previous
      || typeof r.direction !== "string" || !["input", "sent"].includes(r.direction) || !text(r.epoch) || !text(r.stream_id)
      || (r.direction === "sent" ? !text(r.speech_id) : r.speech_id !== null)
      || !uint(r.sample_rate_hz) || r.sample_rate_hz < 1 || r.sample_rate_hz > 192000
      || !uint(r.channels) || ![1, 2].includes(r.channels) || !uint(r.sample_count) || r.sample_count < 1 || r.sample_count > r.sample_rate_hz * 5
      || !uint(r.start_sample) || !uint(r.start_sample + r.sample_count) || !uint(r.generation)
      || !text(r.turn_id) || !(r.response_id === null || text(r.response_id))
      || !uint(r.size_bytes) || r.size_bytes !== r.sample_count * r.channels * 2 + 44 || r.size_bytes > MAX_RECORDING_AUDIO_BYTES
      || typeof r.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(r.sha256)
      || typeof r.duration_ms !== "number" || Math.abs(r.duration_ms - r.sample_count * 1000 / r.sample_rate_hz) > 0.001
      || typeof r.captured_at !== "string" || typeof r.retention_until !== "string"
      || !Number.isFinite(Date.parse(r.captured_at)) || Date.parse(r.retention_until) - Date.parse(r.captured_at) !== 7 * 86400000
      || r.capture_boundary !== (r.direction === "input" ? "validated_input" : "transport_send_completed")
      || r.playback_confirmation !== "not-inferred" || typeof r.pinned !== "boolean" || typeof r.discontinuity !== "boolean" || typeof r.storage_durable !== "boolean"
      || typeof r.status !== "string" || !["available", "expired", "deleted", "unavailable"].includes(r.status)) throw new Error("invalid-row");
    previous = BigInt(r.journal_sequence);
    return { ...Object.fromEntries(keys.map(key => [key, r[key]])), audio_url: `/api/observability/sessions/${encodeURIComponent(sessionId)}/recordings/${encodeURIComponent(r.artifact_id)}/audio` } as unknown as SessionRecordingRow;
  });
  if (value.next_cursor !== null && (!recordingSequence(value.next_cursor) || BigInt(value.next_cursor) <= BigInt(after) || BigInt(value.next_cursor) < previous)) throw new Error("invalid-cursor");
  return { voice_session_id: sessionId, items, next_cursor: value.next_cursor as string | null, storage_status: value.storage_status as SessionRecordingPage["storage_status"],
    ...(value.preservation === undefined ? {} : { preservation: projectRecordingPreservation(value.preservation) }) };
}
