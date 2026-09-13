import { authorizeAvatarAssetRequest, jsonError, validAvatarAssetId } from "@/lib/avatar-assets-server";
import { getTalkingJob, startTalkingJob } from "@/lib/musetalk-talking-worker";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
export async function POST(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许生成讲话素材", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  try { return Response.json({ job: await startTalkingJob(avatarId, avatarActionId) }, { status: 202 }); }
  catch (error) { return jsonError(error instanceof Error ? error.message : "创建任务失败", 400); }
}
export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取任务", 403);
  const { avatarId, avatarActionId } = await context.params;
  return Response.json({ job: await getTalkingJob(avatarId, avatarActionId) }, { headers: { "Cache-Control": "no-store" } });
}
