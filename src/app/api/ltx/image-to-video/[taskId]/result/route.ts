import { NextRequest } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis } from "@/lib/avatar-test-access";
import { downloadLtxResultVideo } from "@/lib/ltx-result-video";
import { getTrustedLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";
import { resolveProviderApiKey, providerKeyFingerprint } from "@/lib/provider-api-key";
import { isMiniMaxModelId } from "@/lib/ltx-avatar-action";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json("不允许从当前来源读取视频生成结果", 403);
  }
  try {
    const { taskId } = await context.params;
    const trusted = getTrustedLocalLtxTask(taskId);
    if (!trusted) return json("视频生成任务不存在、已失效或服务已重启", 404);
    const miniMaxKey = await resolveProviderApiKey(request, "minimax");
    if (isMiniMaxModelId(trusted.model) && trusted.credentialFingerprint !== (miniMaxKey ? providerKeyFingerprint(miniMaxKey) : undefined)) {
      return json("请使用创建任务时的 MiniMax API Key 读取结果", 403);
    }
    const task = await getVideoGeneration(
      {
        LTX_API_KEY: process.env.LTX_API_KEY,
        LTX_API_URL: process.env.LTX_API_URL,
        MINIMAX_API_KEY: miniMaxKey,
        MINIMAX_API_URL: process.env.MINIMAX_API_URL,
      },
      taskId,
      trusted.model,
    );
    if (task.state !== "success" || !task.videoUrl) return json("视频生成结果尚未就绪", 409);
    const result = await downloadLtxResultVideo(task.videoUrl);
    return new Response(result.bytes.slice().buffer as ArrayBuffer, {
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Length": String(result.bytes.byteLength),
        "Content-Type": result.mediaType,
        "Cross-Origin-Resource-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const known = isVideoGenerationProviderError(error);
    return json(known ? error.message : "视频生成结果读取失败", known ? error.status : 502);
  }
}

function json(error: string, status: number) {
  return Response.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
}
