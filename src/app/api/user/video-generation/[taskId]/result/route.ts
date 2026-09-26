import { NextRequest } from "next/server";
import { downloadLtxResultVideo } from "@/lib/ltx-result-video";
import { getTrustedLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";
import { providerKeyFingerprint } from "@/lib/provider-api-key";
import { loadPersonalKey } from "@/lib/user-provider-credentials";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ taskId: string }> };
const json = (error: string, status: number) => Response.json({ error }, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: NextRequest, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return json("请先登录", 401);
  const { taskId } = await context.params;
  const trusted = getTrustedLocalLtxTask(taskId);
  if (!trusted || trusted.visualIdentityId !== `user-upload:${user.issuer}#${user.subject}` || trusted.model !== "MiniMax-H3") return json("找不到生成任务", 404);
  const key = await loadPersonalKey(user, "minimax");
  if (!key || trusted.credentialFingerprint !== providerKeyFingerprint(key)) return json("请使用创建任务时的个人 MiniMax Key", 403);
  try {
    const task = await getVideoGeneration({ MINIMAX_API_KEY: key, MINIMAX_API_URL: process.env.MINIMAX_API_URL }, taskId, trusted.model);
    if (task.state !== "success" || !task.videoUrl) return json("视频生成结果尚未就绪", 409);
    const result = await downloadLtxResultVideo(task.videoUrl);
    return new Response(result.bytes.slice().buffer as ArrayBuffer, { headers: { "Cache-Control": "private, no-store", "Content-Length": String(result.bytes.byteLength), "Content-Type": result.mediaType, "Content-Disposition": "attachment; filename=generated-motion.mp4", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff" } });
  } catch (error) {
    if (isVideoGenerationProviderError(error)) return json(error.message, error.status);
    console.error("Personal MiniMax result download failed with an unexpected error");
    return json("视频生成结果读取失败", 502);
  }
}
