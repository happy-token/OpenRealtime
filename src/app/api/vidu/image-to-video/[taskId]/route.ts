import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis } from "@/lib/avatar-test-access";
import { releaseLocalViduTask } from "@/lib/vidu-task-coordinator";
import { getViduGeneration, ViduProviderError } from "@/lib/vidu-video";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ taskId: string }> },
) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取 Vidu 任务" }, 403);
  }
  try {
    const { taskId } = await context.params;
    const task = await getViduGeneration(
      {
        VIDU_API_KEY: process.env.VIDU_API_KEY,
        VIDU_API_URL: process.env.VIDU_API_URL,
      },
      taskId,
    );
    if (task.state === "success" || task.state === "failed") {
      releaseLocalViduTask(task.taskId);
    }
    return json({
      task_id: task.taskId,
      state: task.state,
      err_code: task.errorCode,
      creations: task.creations.map((creation) => ({
        id: creation.id,
        url: creation.url,
        cover_url: creation.coverUrl,
      })),
    });
  } catch (error) {
    const known = error instanceof ViduProviderError;
    return json(
      { error: known ? error.message : "Vidu 任务查询失败" },
      known ? error.status : 500,
    );
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}
