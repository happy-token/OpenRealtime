import { NextRequest, NextResponse } from "next/server";
import { currentAppAdmin } from "./admin-server";
import { isDiagnosticSessionId, verifyDiagnosticsAccess } from "./diagnostics-access";

export function recordingError(status: number, error = "录音数据暂时不可用") {
  return NextResponse.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
}
/** Header presence is authoritative; an invalid machine grant cannot use cookies. */
export async function authorizeRecording(request: NextRequest, sessionId: string) {
  const authorization = request.headers.get("authorization");
  if (authorization !== null) {
    const token = /^Bearer (\S+)$/i.exec(authorization)?.[1];
    if (!token || !verifyDiagnosticsAccess(token, sessionId, process.env.OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET)) return recordingError(403, "未授权");
  } else {
    try { if (!await currentAppAdmin(request)) return recordingError(403, "未授权"); }
    catch { return recordingError(503, "管理员权限服务暂时不可用"); }
  }
  return isDiagnosticSessionId(sessionId) ? null : recordingError(400, "Session ID 无效");
}

/** Never wait on a noncooperative stream cancellation at the error boundary. */
export function cancelRecordingBody(response: Response | undefined) {
  if (response?.body && !response.body.locked) void response.body.cancel().catch(() => {});
}

export async function boundedRecordingBody(response: Response, max: number, signal: AbortSignal): Promise<Buffer> {
  const length = response.headers.get("content-length");
  if (length !== null && (!/^(0|[1-9][0-9]{0,9})$/.test(length) || Number(length) > max)) { cancelRecordingBody(response); throw new Error("body-size"); }
  if (!response.body) throw new Error("empty-body");
  const reader = response.body.getReader(), chunks: Uint8Array[] = [];
  let total = 0;
  const onAbort = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", onAbort, { once: true });
  try {
    while (true) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      total += value.length;
      if (total > max) throw new Error("body-size");
      chunks.push(value);
    }
    if (length !== null && total !== Number(length)) throw new Error("body-size");
    return Buffer.concat(chunks, total);
  } catch (error) { void reader.cancel().catch(() => {}); throw error; }
  finally { signal.removeEventListener("abort", onAbort); reader.releaseLock(); }
}
export function recordingUpstream(request: NextRequest, sessionId: string, suffix: string) {
  return {
    url: new URL(`/observability/sessions/${encodeURIComponent(sessionId)}/recordings${suffix}`, process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766"),
    signal: AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]),
  };
}
export function upstreamRecordingError(status: number) { return recordingError([404, 410].includes(status) ? status : 503); }
