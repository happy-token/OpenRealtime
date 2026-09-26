import { NextRequest } from "next/server";
import { readPersonalMotionVideo } from "@/lib/personal-motion-library";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ assetId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  try {
    const { assetId } = await context.params;
    const bytes = await readPersonalMotionVideo(user, assetId);
    if (!bytes) return Response.json({ error: "找不到动作素材" }, { status: 404 });
    const preview = request.nextUrl.searchParams.get("preview") === "1";
    const range = preview ? parseByteRange(request.headers.get("range"), bytes.byteLength) : null;
    if (range === "invalid") return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${bytes.byteLength}`, "Cache-Control": "private, no-store" } });
    const content = range ? bytes.subarray(range.start, range.end + 1) : bytes;
    return new Response(content, { status: range ? 206 : 200, headers: {
      "Cache-Control": "private, no-store",
      "Content-Type": "video/mp4",
      "Content-Length": String(content.byteLength),
      "Content-Disposition": `${preview ? "inline" : "attachment"}; filename="motion-${assetId}.mp4"`,
      "Accept-Ranges": "bytes",
      ...(range ? { "Content-Range": `bytes ${range.start}-${range.end}/${bytes.byteLength}` } : {}),
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    return Response.json({ error: "动作素材暂时不可用" }, { status: 503 });
  }
}

function parseByteRange(value: string | null, length: number): { start: number; end: number } | "invalid" | null {
  if (!value) return null;
  const match = /^bytes=(\d+)-(\d*)$/.exec(value);
  if (!match) return "invalid";
  const start = Number(match[1]);
  const end = match[2] ? Number(match[2]) : length - 1;
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= length || end < start) return "invalid";
  return { start, end: Math.min(end, length - 1) };
}
