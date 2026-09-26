import { createHash, randomUUID } from "node:crypto";
import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { createOrReuseLocalLtxTask, getLocalLtxSubmissionByRequestId, LtxTaskSubmissionPendingError } from "@/lib/ltx-task-coordinator";
import { hasMatchingImageSignature } from "@/lib/media-signatures";
import { createImageToVideo, isVideoGenerationProviderError } from "@/lib/video-generation-provider";
import { loadPersonalKey } from "@/lib/user-provider-credentials";
import { userFromRequest } from "@/lib/user-session";
import { providerKeyFingerprint } from "@/lib/provider-api-key";
import { paidGenerationEnabled } from "@/lib/paid-generation-policy";
import { MINIMAX_DURATIONS, type MiniMaxDuration } from "@/lib/minimax-video-options";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const MAX_IMAGE_BYTES = 4_500_000;
const REQUEST_ID = /^[0-9a-f-]{36}$/i;

function ownerId(user: { issuer: string; subject: string }) { return `user-upload:${user.issuer}#${user.subject}`; }
function json(payload: object, status = 200) { return Response.json(payload, { status, headers: { "Cache-Control": "private, no-store" } }); }

export async function GET(request: NextRequest) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const key = await loadPersonalKey(user, "minimax");
  const requestId = request.nextUrl.searchParams.get("request_id");
  if (!requestId) return json({ ready: paidGenerationEnabled() && Boolean(key), configured: Boolean(key), enabled: paidGenerationEnabled() });
  if (!REQUEST_ID.test(requestId)) return json({ error: "生成请求 ID 无效" }, 400);
  const record = getLocalLtxSubmissionByRequestId(requestId);
  if (!record || record.visualIdentityId !== ownerId(user)) return json({ error: "找不到生成任务" }, 404);
  if (!key || record.credentialFingerprint !== providerKeyFingerprint(key)) return json({ error: "请使用创建任务时的个人 MiniMax Key" }, 403);
  return json({ request_id: requestId, submission_state: record.state, task_id: record.task?.taskId, state: record.task?.state || record.state, error: record.state === "submission_unknown" ? "提交结果无法确认；请先核对 MiniMax 任务记录，系统不会自动扣费重试。" : record.error });
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  if (!paidGenerationEnabled()) return json({ error: "生产付费视频任务尚未启用" }, 503);
  const key = await loadPersonalKey(user, "minimax");
  if (!key) return json({ error: "请先在个人设置中保存 MiniMax API Key" }, 409);
  const length = Number(request.headers.get("content-length"));
  if (!Number.isFinite(length) || length <= 0) return json({ error: "请求缺少有效大小" }, 411);
  if (length > MAX_IMAGE_BYTES + 100_000) return json({ error: "图片不能超过 4.5MB" }, 413);
  try {
    const form = await request.formData();
    const image = form.get("image");
    const prompt = form.get("prompt");
    const durationValue = Number(form.get("duration") ?? 4);
    if (!MINIMAX_DURATIONS.includes(durationValue as MiniMaxDuration)) return json({ error: "请选择 4–15 秒的视频时长" }, 400);
    const duration = durationValue as MiniMaxDuration;
    const requestId = form.get("requestId") || randomUUID();
    if (!(image instanceof File) || !["image/jpeg", "image/png", "image/webp"].includes(image.type) || image.size < 100 || image.size > MAX_IMAGE_BYTES) return json({ error: "请上传 4.5MB 内的 JPG、PNG 或 WebP 图片" }, 400);
    if (typeof prompt !== "string" || !prompt.trim() || prompt.length > 2_000) return json({ error: "请填写 2000 字以内的动作提示词" }, 400);
    if (typeof requestId !== "string" || !REQUEST_ID.test(requestId)) return json({ error: "生成请求 ID 无效" }, 400);
    if (form.get("creditsAccepted") !== "true" || form.get("rightsConfirmed") !== "true") return json({ error: "请确认 API 额度与素材使用权" }, 400);
    const bytes = new Uint8Array(await image.arrayBuffer());
    if (!hasMatchingImageSignature(image.type, bytes)) return json({ error: "图片内容与文件类型不符" }, 400);
    const provenance = { visualIdentityId: ownerId(user), credentialFingerprint: providerKeyFingerprint(key), sourceSha256: createHash("sha256").update(bytes).digest("hex"), prompt: prompt.trim(), model: "MiniMax-H3" as const, ratio: "adaptive", resolution: "768P", duration, imageRole: "first_frame" };
    const { task, reused } = await createOrReuseLocalLtxTask(provenance, () => createImageToVideo({ MINIMAX_API_KEY: key, MINIMAX_API_URL: process.env.MINIMAX_API_URL, MINIMAX_UPLOAD_CACHE_PATH: process.env.MINIMAX_UPLOAD_CACHE_PATH }, { imageDataUrl: `data:${image.type};base64,${Buffer.from(bytes).toString("base64")}`, prompt: prompt.trim(), model: "MiniMax-H3", ratio: "adaptive", resolution: "768P", duration, imageRole: "first_frame" }), { requestId });
    return json({ request_id: requestId, task_id: task.taskId, state: task.state, reused }, 202);
  } catch (error) {
    if (error instanceof LtxTaskSubmissionPendingError) return json({ request_id: error.record.requestIds.at(-1), submission_state: error.record.state, error: error.message }, 202);
    if (isVideoGenerationProviderError(error)) return json({ error: error.message }, error.status);
    console.error("Personal MiniMax submission failed with an unexpected error");
    return json({ error: "视频生成任务创建失败" }, 500);
  }
}
