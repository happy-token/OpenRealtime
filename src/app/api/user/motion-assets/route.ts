import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { downloadLtxResultVideo } from "@/lib/ltx-result-video";
import { getTrustedLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { listPersonalMotions, savePersonalMotion } from "@/lib/personal-motion-library";
import { providerKeyFingerprint } from "@/lib/provider-api-key";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { loadPersonalKey } from "@/lib/user-provider-credentials";
import { userFromRequest } from "@/lib/user-session";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (value: object, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: NextRequest) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    return json({ assets: await listPersonalMotions(user) });
  } catch {
    return json({ error: "个人动作素材库暂时不可用" }, 503);
  }
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  let body: { taskId?: unknown } | null;
  try {
    body = await readLimitedJson(request, 1024) as { taskId?: unknown } | null;
  } catch (error) {
    return json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, error instanceof RequestBodyTooLarge ? 413 : 400);
  }
  const taskId = body?.taskId;
  if (typeof taskId !== "string" || !/^[A-Za-z0-9_-]{6,128}$/.test(taskId)) return json({ error: "任务 ID 无效" }, 400);
  const trusted = getTrustedLocalLtxTask(taskId);
  if (!trusted || trusted.visualIdentityId !== `user-upload:${user.issuer}#${user.subject}` || trusted.model !== "MiniMax-H3") return json({ error: "找不到生成任务" }, 404);
  const key = await loadPersonalKey(user, "minimax");
  if (!key || trusted.credentialFingerprint !== providerKeyFingerprint(key)) return json({ error: "请使用创建任务时的个人 MiniMax Key" }, 403);
  try {
    const task = await getVideoGeneration({ MINIMAX_API_KEY: key, MINIMAX_API_URL: process.env.MINIMAX_API_URL }, taskId, trusted.model);
    if (task.state !== "success" || !task.videoUrl) return json({ error: "视频生成结果尚未就绪" }, 409);
    const result = await downloadLtxResultVideo(task.videoUrl);
    if (result.mediaType !== "video/mp4") return json({ error: "仅支持保存 MP4 视频" }, 422);
    const asset = await savePersonalMotion(user, taskId, trusted.prompt, trusted.duration || 4, result.bytes);
    return json({ asset }, 201);
  } catch (error) {
    if (isVideoGenerationProviderError(error)) return json({ error: error.message }, error.status);
    console.error("Failed to save personal motion asset", error);
    return json({ error: "保存动作素材失败" }, 502);
  }
}
