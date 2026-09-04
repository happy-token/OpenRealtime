import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { Readable } from "node:stream";
import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis } from "@/lib/avatar-test-access";
import { parseByteRange } from "@/lib/avatar-evaluation-artifacts";
import {
  getLivePortraitTask,
  retainLivePortraitTaskArtifact,
} from "@/lib/liveportrait-worker";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取 LivePortrait 任务" }, 403);
  }
  const { taskId } = await context.params;
  if (!/^[a-f0-9-]{36}$/.test(taskId)) return json({ error: "LivePortrait 任务 ID 无效" }, 400);
  const task = getLivePortraitTask(taskId);
  if (!task) return json({ error: "LivePortrait 任务不存在或服务已重启" }, 404);
  if (request.nextUrl.searchParams.get("artifact") === "1") {
    if (task.state !== "success" || !task.resultPath) return json({ error: "LivePortrait 结果尚未就绪" }, 409);
    return streamVideo(request, task.id, task.resultPath);
  }
  return json({
    task_id: task.id,
    state: task.state,
    driver_id: task.driverId,
    source_name: task.sourceName,
    created_at: task.createdAt,
    updated_at: task.updatedAt,
    render_seconds: task.renderSeconds,
    device: task.device,
    error: task.error,
    result_url: task.state === "success" ? `/api/liveportrait/${task.id}?artifact=1` : undefined,
  });
}

async function streamVideo(request: Request, taskId: string, filePath: string) {
  const releaseArtifact = retainLivePortraitTaskArtifact(taskId);
  if (!releaseArtifact) return json({ error: "LivePortrait 结果文件不可用" }, 404);
  try {
    const fileStats = await stat(filePath);
    const rangeHeader = request.headers.get("range");
    const range = rangeHeader ? parseByteRange(rangeHeader, fileStats.size) : null;
    if (rangeHeader && !range) {
      releaseArtifact();
      return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${fileStats.size}` } });
    }
    const start = range?.start ?? 0;
    const end = range?.end ?? fileStats.size - 1;
    const fileStream = createReadStream(filePath, { start, end });
    fileStream.once("close", releaseArtifact);
    fileStream.once("error", releaseArtifact);
    const body = Readable.toWeb(fileStream) as ReadableStream<Uint8Array>;
    const headers: Record<string, string> = {
      "Accept-Ranges": "bytes",
      "Cache-Control": "private, no-store",
      "Content-Length": String(end - start + 1),
      "Content-Type": "video/mp4",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    };
    if (range) headers["Content-Range"] = `bytes ${start}-${end}/${fileStats.size}`;
    return new Response(body, { status: range ? 206 : 200, headers });
  } catch {
    releaseArtifact();
    return json({ error: "LivePortrait 结果文件不可用" }, 404);
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}
