import { NextRequest } from "next/server";
import { getTrustedLocalLtxTask, releaseLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";
import { providerKeyFingerprint } from "@/lib/provider-api-key";
import { loadPersonalKey } from "@/lib/user-provider-credentials";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ taskId: string }> };
const json = (payload: object, status = 200) => Response.json(payload, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: NextRequest, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { taskId } = await context.params;
  const trusted = getTrustedLocalLtxTask(taskId);
  if (!trusted || trusted.visualIdentityId !== `user-upload:${user.issuer}#${user.subject}` || trusted.model !== "MiniMax-H3") return json({ error: "找不到生成任务" }, 404);
  const key = await loadPersonalKey(user, "minimax");
  if (!key || trusted.credentialFingerprint !== providerKeyFingerprint(key)) return json({ error: "请使用创建任务时的个人 MiniMax Key" }, 403);
  try {
    const task = await getVideoGeneration({ MINIMAX_API_KEY: key, MINIMAX_API_URL: process.env.MINIMAX_API_URL }, taskId, trusted.model);
    if (task.state === "success" || task.state === "failed") await releaseLocalLtxTask(taskId, task.state);
    return json({ task_id: task.taskId, state: task.state, error: task.error, result_url: task.state === "success" ? `/api/user/video-generation/${encodeURIComponent(taskId)}/result` : undefined });
  } catch (error) {
    if (isVideoGenerationProviderError(error)) return json({ error: error.message }, error.status);
    console.error("Personal MiniMax task query failed with an unexpected error");
    return json({ error: "视频生成任务查询失败" }, 502);
  }
}
