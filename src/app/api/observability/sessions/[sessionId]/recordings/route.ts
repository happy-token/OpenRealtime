import { NextRequest, NextResponse } from "next/server";
import { authorizeRecording, boundedRecordingBody, cancelRecordingBody, recordingError, recordingUpstream, upstreamRecordingError } from "@/lib/recording-access-server";
import { projectRecordingPage, recordingSequence } from "@/lib/session-recordings";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const denied = await authorizeRecording(request, sessionId);
  if (denied) return denied;
  const query = request.nextUrl.searchParams, after = query.get("after_sequence") ?? "0", size = query.get("limit") ?? "200";
  if (query.getAll("after_sequence").length > 1 || query.getAll("limit").length > 1 || !recordingSequence(after) || !/^[1-9][0-9]{0,2}$/.test(size) || Number(size) > 200) return recordingError(400, "录音分页参数无效");
  const { url, signal } = recordingUpstream(request, sessionId, `?after_sequence=${after}&limit=${size}`);
  let response: Response | undefined;
  try {
    response = await fetch(url, { cache: "no-store", signal });
    if (!response.ok) return upstreamRecordingError(response.status);
    const body = await boundedRecordingBody(response, 1024 * 1024, signal);
    return NextResponse.json(projectRecordingPage(JSON.parse(body.toString("utf8")), sessionId, after, Number(size)), { headers: { "Cache-Control": "no-store" } });
  } catch { return recordingError(503); }
  finally { cancelRecordingBody(response); }
}
