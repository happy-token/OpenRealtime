import { isSameOriginAvatarMutation } from "./avatar-test-access";
import { hasMatchingAudioSignature } from "./media-signatures";
import { findPersonalAvatar } from "./personal-avatar-library";
import { getPersonalTalkingJob, resumePersonalTalkingJob, startPersonalTalkingJob } from "./personal-talking-worker";
import { readBuiltInTalkingAudio } from "./talking-reference-audio";
import type { PersonalTalkingKind } from "./user-talking-model-services";
import { userFromRequest } from "./user-session";

type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });
const AUDIO_TYPES = new Set(["audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp4", "audio/x-m4a"]);

export async function getPersonalTalking(request: Request, context: Context, kind: PersonalTalkingKind) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { avatarId, avatarActionId } = await context.params;
  const avatar = await findPersonalAvatar(user, avatarId);
  if (!avatar || avatar.deletedAt || !avatar.actions.some((action) => action.avatar_action_id === avatarActionId && !action.deleted_at)) return json({ error: "找不到动作底片" }, 404);
  return json({ job: await getPersonalTalkingJob(user, kind, avatarId, avatarActionId) });
}

export async function postPersonalTalking(request: Request, context: Context, kind: PersonalTalkingKind) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { avatarId, avatarActionId } = await context.params;
  const avatar = await findPersonalAvatar(user, avatarId);
  if (!avatar || avatar.deletedAt || !avatar.actions.some((action) => action.avatar_action_id === avatarActionId && !action.deleted_at && action.video_url)) return json({ error: "找不到动作底片" }, 404);
  const length = Number(request.headers.get("content-length"));
  if (Number.isFinite(length) && length > 21 * 1024 * 1024) return json({ error: "请求内容过大" }, 413);
  try {
    const existing = await getPersonalTalkingJob(user, kind, avatarId, avatarActionId);
    if (existing?.state === "failed" && existing.retryBlocked) return json({ job: await resumePersonalTalkingJob(user, kind, avatarId, avatarActionId) }, 202);
    if (existing && ["queued", "processing", "ready_for_review"].includes(existing.state)) return json({ job: existing }, 202);
    if (!request.headers.get("content-type")?.startsWith("multipart/form-data")) return json({ error: "请提交参考音频表单" }, 400);
    const form = await request.formData();
    const uploaded = form.get("audio");
    let audio: Buffer | undefined;
    if (uploaded instanceof File) {
      const mediaType = uploaded.type.toLowerCase().split(";", 1)[0];
      if (!AUDIO_TYPES.has(mediaType) || !uploaded.size || uploaded.size > 20 * 1024 * 1024 || !/\.(wav|mp3|m4a)$/i.test(uploaded.name)) return json({ error: "参考音频格式或大小无效" }, 400);
      audio = Buffer.from(await uploaded.arrayBuffer());
      if (!hasMatchingAudioSignature(mediaType, audio)) return json({ error: "参考音频内容与格式不匹配" }, 400);
    }
    if (!audio && form.get("audioSource") === "builtin") audio = await readBuiltInTalkingAudio();
    if (kind === "wav2lip" && !audio) return json({ error: "Wav2Lip 请上传参考音频" }, 400);
    const job = await startPersonalTalkingJob({
      user, kind, avatarId, actionId: avatarActionId, audio,
      rightsConfirmed: form.get("rightsConfirmed") === "true",
      usageScope: String(form.get("usageScope") || ""),
    });
    return json({ job }, 202);
  } catch (error) {
    const message = error instanceof Error ? error.message : "创建任务失败";
    return json({ error: message }, /尚未配置|未就绪/.test(message) ? 503 : 400);
  }
}
