export interface InputEvidenceRecord {
  item_id: string;
  voice_session_id: string;
  sequence: string;
  occurred_at: string;
  detail: Record<string, unknown>;
}
export interface SessionInputEvidencePage {
  schema: "semantic-input-evidence.v1";
  voice_session_id: string;
  records: InputEvidenceRecord[];
  next_cursor: string | null;
  durable: boolean;
  status: "available" | "not_collected";
}
export const validEvidenceSequence = (value: unknown): value is string => typeof value === "string"
  && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= BigInt("9223372036854775807");
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;

/** Reject the whole source on scope/order/content faults; never expose a partial unsafe page. */
export function parseInputEvidencePage(value: unknown, sessionId: string, after: string): SessionInputEvidencePage {
  if (!object(value) || value.schema !== "semantic-input-evidence.v1" || value.voice_session_id !== sessionId
    || !Array.isArray(value.records) || value.records.length > 100 || typeof value.durable !== "boolean"
    || typeof value.status !== "string" || !["available", "not_collected"].includes(value.status)) throw new Error("unavailable");
  let previous = BigInt(after);
  const ids = new Set<string>();
  const records: InputEvidenceRecord[] = value.records.map(row => {
    if (!object(row) || row.voice_session_id !== sessionId || !text(row.item_id) || ids.has(row.item_id)
      || !validEvidenceSequence(row.sequence) || BigInt(row.sequence) <= previous
      || !text(row.occurred_at) || !Number.isFinite(Date.parse(row.occurred_at)) || !object(row.detail)) throw new Error("unavailable");
    const detail = row.detail;
    if (detail.schema !== "semantic-input-evidence.v1" || !text(detail.input_id) || !text(detail.event)
      || !text(detail.source_thread_id) || !text(detail.turn_id) || !Number.isSafeInteger(detail.generation)
      || Number(detail.generation) < 0 || typeof detail.durable !== "boolean") throw new Error("unavailable");
    previous = BigInt(row.sequence); ids.add(row.item_id);
    return { item_id: row.item_id, voice_session_id: sessionId, sequence: row.sequence,
      occurred_at: row.occurred_at, detail };
  });
  if (value.next_cursor !== null && (!validEvidenceSequence(value.next_cursor) || !records.length
    || BigInt(value.next_cursor) !== previous)) throw new Error("unavailable");
  if (value.status === "not_collected" && (records.length || value.next_cursor !== null)) throw new Error("unavailable");
  return { schema: "semantic-input-evidence.v1", voice_session_id: sessionId, records,
    next_cursor: value.next_cursor as string | null, durable: value.durable,
    status: value.status as SessionInputEvidencePage["status"] };
}
