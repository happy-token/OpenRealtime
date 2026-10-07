import { NextRequest, NextResponse } from "next/server";
import { recordingPreservationAdmin, preservationWriteProof } from "@/lib/recording-preservation-server";
import { projectPreservationResult } from "@/lib/recording-preservation";
import { boundedRecordingBody, cancelRecordingBody, recordingError, recordingUpstream } from "@/lib/recording-access-server";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function POST(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const admin = await recordingPreservationAdmin(request, sessionId);
  if (admin instanceof Response) return admin;
  if (request.nextUrl.search) return recordingError(400, "保留请求不接受客户端参数");
  let response: Response | undefined;
  try {
    const { url, signal } = recordingUpstream(request, sessionId, "/preservation");
    if (request.body !== null) {
      try { await boundedRecordingBody(new Response(request.body), 0, signal); }
      catch { return recordingError(400, "保留请求不接受客户端参数"); }
    }
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password) throw new Error("invalid-private-url");
    const proof = preservationWriteProof(admin, sessionId);
    response = await fetch(url, { method: "POST", ...proof, cache: "no-store", redirect: "error", signal });
    if (!response.ok) return recordingError([404, 409].includes(response.status) ? response.status : 503, "保留结果尚未确认，请刷新录音目录核查");
    const body = await boundedRecordingBody(response, 16 * 1024, signal);
    return NextResponse.json(projectPreservationResult(JSON.parse(body.toString("utf8")), sessionId), { headers: { "Cache-Control": "no-store" } });
  } catch { return recordingError(503, "保留结果尚未确认，请刷新录音目录核查"); }
  finally { cancelRecordingBody(response); }
}
