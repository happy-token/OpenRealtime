import { authorizeAvatarAssetRequest, jsonError, validAvatarAssetId } from "@/lib/avatar-assets-server";
import { getTalkingJob, startTalkingJob } from "@/lib/musetalk-talking-worker";
import { hasMatchingAudioSignature } from "@/lib/media-signatures";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
export async function POST(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许生成口型对齐", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  try {
    let uploadedAudio: Buffer | undefined;
    if (request.headers.get("content-type")?.startsWith("multipart/form-data")) {
      const form = await request.formData();
      const audio = form.get("audio");
      if (audio instanceof File) {
        const mediaType = audio.type.toLowerCase().split(";", 1)[0];
        if (!["audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"].includes(mediaType) || !audio.size || audio.size > 20 * 1024 * 1024) return jsonError("参考音频格式或大小无效", 400);
        uploadedAudio = Buffer.from(await audio.arrayBuffer());
        if (!hasMatchingAudioSignature(mediaType, uploadedAudio)) return jsonError("参考音频内容与格式不匹配", 400);
      }
    }
    return Response.json({ job: await startTalkingJob(avatarId, avatarActionId, new URL(request.url).searchParams.get("preview") === "true", uploadedAudio) }, { status: 202 });
  }
  catch (error) { return jsonError(error instanceof Error ? error.message : "创建任务失败", 400); }
}
export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取任务", 403);
  const { avatarId, avatarActionId } = await context.params;
  return Response.json({ job: await getTalkingJob(avatarId, avatarActionId) }, { headers: { "Cache-Control": "no-store" } });
}
