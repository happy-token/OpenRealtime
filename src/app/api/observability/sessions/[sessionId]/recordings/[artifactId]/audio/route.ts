import { createHash } from "node:crypto";
import { NextRequest } from "next/server";
import { isDiagnosticSessionId } from "@/lib/diagnostics-access";
import { authorizeRecording, boundedRecordingBody, cancelRecordingBody, recordingError, recordingUpstream, upstreamRecordingError } from "@/lib/recording-access-server";
import { MAX_RECORDING_AUDIO_BYTES } from "@/lib/session-recordings";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string; artifactId: string }> }) {
  const { sessionId, artifactId } = await context.params;
  const denied = await authorizeRecording(request, sessionId);
  if (denied) return denied;
  if (!isDiagnosticSessionId(artifactId)) return recordingError(400, "录音 ID 无效");
  const { url, signal } = recordingUpstream(request, sessionId, `/${encodeURIComponent(artifactId)}/audio`);
  let response: Response | undefined;
  try {
    response = await fetch(url, { cache: "no-store", signal });
    if (!response.ok) return upstreamRecordingError(response.status);
    const hash = response.headers.get("x-recording-sha256"), length = response.headers.get("content-length");
    if (response.headers.get("x-recording-session") !== sessionId || response.headers.get("x-recording-artifact") !== artifactId
      || response.headers.get("content-type") !== "audio/wav" || !hash || !/^[a-f0-9]{64}$/.test(hash) || !length || !/^[1-9][0-9]{0,9}$/.test(length)
      || Number(length) <= 44 || Number(length) > MAX_RECORDING_AUDIO_BYTES) return recordingError(503);
    const data = await boundedRecordingBody(response, MAX_RECORDING_AUDIO_BYTES, signal);
    if (createHash("sha256").update(data).digest("hex") !== hash) return recordingError(503);
    const headers = { "Content-Type": "audio/wav", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "bytes" };
    const range = request.headers.get("range");
    if (range === null) return new Response(new Uint8Array(data), { headers: { ...headers, "Content-Length": String(data.length) } });
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    let start = -1, end = -1;
    if (match && (match[1] || match[2]) && match.slice(1).every(value => !value || Number.isSafeInteger(Number(value)))) {
      start = match[1] ? Number(match[1]) : Math.max(0, data.length - Number(match[2]));
      end = match[1] && match[2] ? Math.min(Number(match[2]), data.length - 1) : data.length - 1;
      if (!match[1] && Number(match[2]) === 0) start = -1;
    }
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start >= data.length || end < start) return new Response(null, { status: 416, headers: { ...headers, "Content-Range": `bytes */${data.length}` } });
    return new Response(new Uint8Array(data.subarray(start, end + 1)), { status: 206, headers: { ...headers, "Content-Length": String(end - start + 1), "Content-Range": `bytes ${start}-${end}/${data.length}` } });
  } catch { return recordingError(503); }
  finally { cancelRecordingBody(response); }
}
