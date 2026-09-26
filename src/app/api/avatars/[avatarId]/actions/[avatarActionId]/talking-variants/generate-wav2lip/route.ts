import { authorizeAvatarAssetRequest, jsonError, validAvatarAssetId } from "@/lib/avatar-assets-server";
import { getWav2LipJob, MAX_REQUEST_BYTES, startWav2LipJob } from "@/lib/wav2lip-talking-worker";
import { readBuiltInTalkingAudio } from "@/lib/talking-reference-audio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };

export async function POST(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许生成口型对齐", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  const contentLength = Number(request.headers.get("content-length"));
  if (!Number.isFinite(contentLength) || contentLength <= 0) return jsonError("上传请求缺少有效大小", 411);
  if (contentLength > MAX_REQUEST_BYTES) return jsonError("参考音频不能超过 20MB", 413);
  try {
    const form = await request.formData();
    const uploaded = form.get("audio");
    const audio = uploaded instanceof File ? uploaded : form.get("audioSource") === "builtin"
      ? new File([Uint8Array.from(await readBuiltInTalkingAudio())], "reference.wav", { type: "audio/wav" }) : null;
    if (!audio) return jsonError("请选择参考音频", 400);
    const job = await startWav2LipJob({ avatarId, actionId: avatarActionId, audio, rightsConfirmed: form.get("rightsConfirmed") === "true", usageScope: String(form.get("usageScope") || ""), previewOnly: new URL(request.url).searchParams.get("preview") === "true" });
    return Response.json({ job }, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return jsonError(error instanceof Error ? error.message : "创建任务失败", 400); }
}

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取任务", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  return Response.json({ job: await getWav2LipJob(avatarId, avatarActionId) }, { headers: { "Cache-Control": "no-store" } });
}
