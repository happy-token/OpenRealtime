import { authorizeAvatarAssetRequest, jsonError, validAvatarAssetId } from "@/lib/avatar-assets-server";
import { acceptTalkingJob } from "@/lib/musetalk-talking-worker";
import { acceptWav2LipJob } from "@/lib/wav2lip-talking-worker";
import { acceptLipForcingJob } from "@/lib/lipforcing-talking-worker";

export const runtime = "nodejs";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };

export async function POST(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许保存口型对齐", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  try {
    const body = await request.text();
    if (body.length > 256) return jsonError("参数过大", 400);
    const { jobId } = JSON.parse(body) as { jobId?: unknown };
    if (typeof jobId !== "string") return jsonError("任务 ID 无效", 400);
    const result = jobId.startsWith("musetalk-")
      ? await acceptTalkingJob(avatarId, avatarActionId, jobId)
      : jobId.startsWith("wav2lip-") ? await acceptWav2LipJob(avatarId, avatarActionId, jobId)
      : jobId.startsWith("lipforcing-") ? await acceptLipForcingJob(avatarId, avatarActionId, jobId) : null;
    if (!result) return jsonError("任务 ID 无效", 400);
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "保存失败", 400);
  }
}
