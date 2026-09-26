import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { hasMatchingAudioSignature } from "@/lib/media-signatures";
import { findPersonalAvatar } from "@/lib/personal-avatar-library";
import { findPersonalRole } from "@/lib/personal-role-library";
import { getLipForcingJob, resumeLipForcingJob, startLipForcingJob } from "@/lib/lipforcing-talking-worker";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
const AUDIO_TYPES = new Set(["audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"]);
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: Request, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { avatarId, avatarActionId } = await context.params;
  const avatar = await findPersonalAvatar(user, avatarId);
  if (!avatar || avatar.deletedAt || !avatar.actions.some((item) => item.avatar_action_id === avatarActionId && !item.deleted_at)) return json({ error: "找不到动作底片" }, 404);
  return json({ job: await getLipForcingJob(avatarId, avatarActionId) });
}

export async function POST(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { avatarId, avatarActionId } = await context.params;
  const avatar = await findPersonalAvatar(user, avatarId);
  if (!avatar || avatar.deletedAt || !avatar.actions.some((item) => item.avatar_action_id === avatarActionId && !item.deleted_at && item.video_url)) return json({ error: "找不到动作底片" }, 404);
  try {
    const existing = await getLipForcingJob(avatarId, avatarActionId);
    if (existing?.state === "failed" && existing.retryBlocked) return json({ job: await resumeLipForcingJob(avatarId, avatarActionId, user) }, 202);
    if (existing && (existing.state === "queued" || existing.state === "processing" || existing.state === "ready_for_review")) return json({ job: existing }, 202);
    const form = await request.formData();
    const uploaded = form.get("audio");
    let referenceAudio: Buffer;
    if (uploaded instanceof File) {
      const mediaType = uploaded.type.toLowerCase().split(";", 1)[0];
      if (!AUDIO_TYPES.has(mediaType) || !uploaded.size || uploaded.size > 20 * 1024 * 1024) return json({ error: "参考音频格式或大小无效" }, 400);
      referenceAudio = Buffer.from(await uploaded.arrayBuffer());
      if (!hasMatchingAudioSignature(mediaType, referenceAudio)) return json({ error: "参考音频内容与格式不匹配" }, 400);
    } else {
      const roleId = form.get("roleId");
      if (typeof roleId !== "string") return json({ error: "请选择角色或上传参考音频" }, 400);
      const role = await findPersonalRole(user, roleId);
      if (!role || role.avatar_id !== avatarId) return json({ error: "角色与数字人形象不匹配" }, 400);
      const base = process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";
      const url = new URL("/tts/preview", base);
      url.search = new URLSearchParams({ provider: role.voice_provider, voice: role.voice_id, speech_rate: "0", dialect: role.voice_dialect ?? "" }).toString();
      const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(45_000) });
      if (!response.ok || !response.headers.get("content-type")?.includes("audio/wav")) throw new Error("当前角色声音暂时无法生成参考音频，请上传音频后重试");
      referenceAudio = Buffer.from(await response.arrayBuffer());
      if (referenceAudio.length > 20 * 1024 * 1024 || !hasMatchingAudioSignature("audio/wav", referenceAudio)) throw new Error("参考音频无效");
    }
    return json({ job: await startLipForcingJob(avatarId, avatarActionId, referenceAudio, user) }, 202);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Lip Forcing 任务创建失败";
    return json({ error: message }, /尚未配置|暂时无法|生成参考音频/.test(message) ? 503 : 400);
  }
}
