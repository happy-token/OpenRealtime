import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis } from "@/lib/avatar-test-access";
import { getTrustedLocalLtxTask, releaseLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取视频生成任务" }, 403);
  }
  try {
    const { taskId } = await context.params;
    const trusted = getTrustedLocalLtxTask(taskId);
    if (!trusted) return json({ error: "视频生成任务不存在、已失效或服务已重启" }, 404);
    const task = await getVideoGeneration(
      {
        LTX_API_KEY: process.env.LTX_API_KEY,
        LTX_API_URL: process.env.LTX_API_URL,
        MINIMAX_API_KEY: process.env.MINIMAX_API_KEY,
        MINIMAX_API_URL: process.env.MINIMAX_API_URL,
        MINIMAX_UPLOAD_CACHE_PATH: process.env.MINIMAX_UPLOAD_CACHE_PATH,
      },
      taskId,
      trusted.model,
    );
    if (task.state === "success" || task.state === "failed") releaseLocalLtxTask(taskId);
    return json({
      task_id: task.taskId,
      state: task.state,
      model: trusted.model,
      error: task.error,
      result_url: task.state === "success"
        ? `/api/ltx/image-to-video/${encodeURIComponent(taskId)}/result`
        : undefined,
    });
  } catch (error) {
    const known = isVideoGenerationProviderError(error);
    return json({ error: known ? error.message : "视频生成任务查询失败" }, known ? error.status : 500);
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}
