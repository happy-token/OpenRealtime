import { readFile, stat } from "node:fs/promises";
import { findPersonalAvatar } from "@/lib/personal-avatar-library";
import { getLipForcingJob, privateLipForcingOutput } from "@/lib/lipforcing-talking-worker";
import { getPersonalTalkingJob, privatePersonalTalkingOutput } from "@/lib/personal-talking-worker";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string; variantId: string }> };

export async function GET(request: Request, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  const { avatarId, avatarActionId, variantId: jobId } = await context.params;
  if (!/^(lipforcing|musetalk|wav2lip)-[0-9a-f-]{36}$/.test(jobId)) return Response.json({ error: "任务 ID 无效" }, { status: 400 });
  const avatar = await findPersonalAvatar(user, avatarId);
  const action = avatar?.actions.find((item) => item.avatar_action_id === avatarActionId && !item.deleted_at);
  const kind = jobId.startsWith("musetalk-") ? "musetalk" : jobId.startsWith("wav2lip-") ? "wav2lip" : null;
  const job = action ? kind ? await getPersonalTalkingJob(user, kind, avatarId, avatarActionId)
    : await getLipForcingJob(avatarId, avatarActionId) : null;
  if (!avatar || avatar.deletedAt || !action || !job || job.id !== jobId || !["ready_for_review", "success"].includes(job.state)) return Response.json({ error: "找不到讲话视频" }, { status: 404 });
  const output = kind ? privatePersonalTalkingOutput(user, jobId) : privateLipForcingOutput(user, jobId);
  const file = await stat(output).catch(() => null);
  if (!file?.isFile() || file.size > 200 * 1024 * 1024) return Response.json({ error: "讲话视频不可用" }, { status: 404 });
  const bytes = await readFile(output);
  const match = /^bytes=(\d+)-(\d*)$/.exec(request.headers.get("range") ?? "");
  const start = match ? Number(match[1]) : 0;
  const end = match ? Math.min(match[2] ? Number(match[2]) : bytes.length - 1, bytes.length - 1) : bytes.length - 1;
  if (start >= bytes.length || end < start) return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${bytes.length}` } });
  const content = bytes.subarray(start, end + 1);
  return new Response(content, { status: match ? 206 : 200, headers: {
    "Content-Type": "video/mp4", "Content-Length": String(content.length), "Accept-Ranges": "bytes",
    "Cache-Control": "private, no-store", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
    ...(match ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}),
  } });
}
