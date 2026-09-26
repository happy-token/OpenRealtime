import { authorizeAvatarAssetRequest, jsonError, validAvatarAssetId } from "@/lib/avatar-assets-server";
import { hasMatchingAudioSignature } from "@/lib/media-signatures";
import { getLipForcingJob, resumeLipForcingJob, startLipForcingJob } from "@/lib/lipforcing-talking-worker";
import { findPersonalRole } from "@/lib/personal-role-library";
import { findRole } from "@/lib/role-catalog-repository";
import { userFromRequest } from "@/lib/user-session";
import { readBuiltInTalkingAudio } from "@/lib/talking-reference-audio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
const MAX_AUDIO_BYTES = 20 * 1024 * 1024;
const AUDIO_TYPES = new Set(["audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"]);

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Lip Forcing 任务", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  return Response.json({ job: await getLipForcingJob(avatarId, avatarActionId) }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许生成 Lip Forcing 口型对齐", 403);
  const { avatarId, avatarActionId } = await context.params;
  if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(avatarActionId)) return jsonError("动作标识无效", 400);
  try {
    const existing = await getLipForcingJob(avatarId, avatarActionId);
    if (existing?.state === "failed" && existing.retryBlocked) {
      return Response.json({ job: await resumeLipForcingJob(avatarId, avatarActionId) }, { status: 202 });
    }
    if (existing && (existing.state === "queued" || existing.state === "processing" || existing.state === "ready_for_review")) {
      return Response.json({ job: existing }, { status: 202 });
    }
    const form = request.headers.get("content-type")?.startsWith("multipart/form-data") ? await request.formData() : null;
    const uploaded = form?.get("audio");
    let referenceAudio: Buffer;
    if (uploaded instanceof File) {
      const mediaType = uploaded.type.toLowerCase().split(";", 1)[0];
      if (!AUDIO_TYPES.has(mediaType) || !uploaded.size || uploaded.size > MAX_AUDIO_BYTES) return jsonError("参考音频格式或大小无效", 400);
      referenceAudio = Buffer.from(await uploaded.arrayBuffer());
      if (!hasMatchingAudioSignature(mediaType, referenceAudio)) return jsonError("参考音频内容与格式不匹配", 400);
    } else if (form?.get("audioSource") === "builtin") {
      referenceAudio = await readBuiltInTalkingAudio();
    } else {
      const roleId = form?.get("roleId");
      if (typeof roleId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(roleId)) return jsonError("请选择角色或上传参考音频", 400);
      const user = await userFromRequest(request);
      const role = roleId.startsWith("role-personal-")
        ? user ? await findPersonalRole(user, roleId) : null
        : await findRole(roleId);
      if (!role || role.avatar_id !== avatarId) return jsonError("角色与数字人形象不匹配", 400);
      const base = process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";
      const url = new URL("/tts/preview", base);
      url.search = new URLSearchParams({ provider: role.voice_provider, voice: role.voice_id, speech_rate: "0", dialect: role.voice_dialect ?? "" }).toString();
      const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(45_000) });
      if (!response.ok || !response.headers.get("content-type")?.includes("audio/wav")) throw new Error("当前角色声音暂时无法生成参考音频，请上传音频后重试");
      referenceAudio = Buffer.from(await response.arrayBuffer());
      if (referenceAudio.length > MAX_AUDIO_BYTES || !hasMatchingAudioSignature("audio/wav", referenceAudio)) throw new Error("参考音频无效");
    }
    return Response.json({ job: await startLipForcingJob(avatarId, avatarActionId, referenceAudio) }, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Lip Forcing 任务创建失败";
    return jsonError(message, /尚未配置|暂时无法|生成参考音频/.test(message) ? 503 : 400);
  }
}
