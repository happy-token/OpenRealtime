import { readFile, stat } from "node:fs/promises";
import {
  authorizeAvatarAssetRequest,
  avatarAssetJsonResponse,
  jsonError,
  persistAvatarCandidate,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";
import { getLivePortraitTask, retainLivePortraitTaskArtifact } from "@/lib/liveportrait-worker";
import { hasMatchingVideoSignature } from "@/lib/media-signatures";
import { getTrustedLocalViduTask } from "@/lib/vidu-task-coordinator";
import { assertSafeViduResultUrl } from "@/lib/vidu-result-url";
import { getViduGeneration, ViduProviderError } from "@/lib/vidu-video";
import { downloadLtxResultVideo } from "@/lib/ltx-result-video";
import { getTrustedLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { getVideoGeneration, isVideoGenerationProviderError } from "@/lib/video-generation-provider";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_VIDEO_BYTES = 50 * 1024 * 1024;

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) {
    return jsonError("不允许从当前来源保存 Provider 候选", 403);
  }
  try {
    const payload = await request.json() as {
      sourceKind?: unknown;
      taskId?: unknown;
      avatarId?: unknown;
      idempotencyKey?: unknown;
      rightsConfirmed?: unknown;
    };
    if (
      (payload.sourceKind !== "vidu" && payload.sourceKind !== "liveportrait" && payload.sourceKind !== "ltx" && payload.sourceKind !== "minimax")
      || !validAvatarAssetId(payload.taskId)
      || !validAvatarAssetId(payload.avatarId)
      || !validAvatarAssetId(payload.idempotencyKey)
    ) {
      return jsonError("Provider 候选请求无效", 400);
    }
    if (payload.rightsConfirmed !== true) {
      return jsonError("请先确认生成结果仅用于当前内部效果测试", 400);
    }
    const result = payload.sourceKind === "vidu"
      ? await readViduResult(payload.taskId)
      : payload.sourceKind === "ltx" || payload.sourceKind === "minimax"
        ? await readVideoGenerationResult(payload.taskId)
        : await readLivePortraitResult(payload.taskId);
    if (payload.avatarId !== result.visualIdentityId) {
      return jsonError("Provider 任务与当前数字人身份不匹配", 409);
    }
    const candidateSourceKind = payload.sourceKind === "minimax" ? "ltx" : payload.sourceKind;
    const response = await persistAvatarCandidate({
      avatarId: result.visualIdentityId,
      sourceKind: candidateSourceKind,
      sourceId: payload.taskId,
      logicalName: `${payload.sourceKind}-${payload.taskId}.mp4`,
      mediaType: result.mediaType,
      idempotencyKey: payload.idempotencyKey,
      bytes: result.bytes,
    });
    return avatarAssetJsonResponse(response, await response.text());
  } catch (error) {
    const known = error instanceof ViduProviderError || isVideoGenerationProviderError(error);
    console.error("Failed to persist provider Motion Base Candidate", error);
    return jsonError(
      known ? error.message : "Provider 候选保存失败",
      known ? error.status : 503,
    );
  }
}

async function readVideoGenerationResult(taskId: string) {
  const trustedTask = getTrustedLocalLtxTask(taskId);
  if (!trustedTask) throw new Error("视频生成任务不存在、已失效或不是由当前服务创建");
  const task = await getVideoGeneration({
    LTX_API_KEY: process.env.LTX_API_KEY,
    LTX_API_URL: process.env.LTX_API_URL,
    MINIMAX_API_KEY: process.env.MINIMAX_API_KEY,
    MINIMAX_API_URL: process.env.MINIMAX_API_URL,
    MINIMAX_UPLOAD_CACHE_PATH: process.env.MINIMAX_UPLOAD_CACHE_PATH,
  }, taskId, trustedTask.model);
  if (task.state !== "success" || !task.videoUrl) {
    throw new Error("视频生成任务尚未成功或没有可保存的视频");
  }
  const result = await downloadLtxResultVideo(task.videoUrl);
  return { ...result, visualIdentityId: trustedTask.visualIdentityId };
}

async function readViduResult(taskId: string) {
  const trustedTask = getTrustedLocalViduTask(taskId);
  if (!trustedTask) throw new Error("Vidu 任务不存在、已失效或不是由当前服务创建");
  const task = await getViduGeneration({
    VIDU_API_KEY: process.env.VIDU_API_KEY,
    VIDU_API_URL: process.env.VIDU_API_URL,
  }, taskId);
  if (task.state !== "success" || !task.creations[0]) {
    throw new Error("Vidu 任务尚未成功或没有可保存的视频");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const safeUrl = await assertSafeViduResultUrl(task.creations[0].url);
    const response = await fetch(safeUrl, {
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error("Vidu 结果下载失败");
    const bytes = await readBoundedBody(response);
    return {
      bytes,
      mediaType: identifyVideoType(response.headers.get("content-type"), bytes),
      visualIdentityId: trustedTask.visualIdentityId,
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function readLivePortraitResult(taskId: string) {
  const task = getLivePortraitTask(taskId);
  if (!task || task.state !== "success" || !task.resultPath) {
    throw new Error("LivePortrait 任务不存在、已失效或尚未成功");
  }
  const release = retainLivePortraitTaskArtifact(taskId);
  if (!release) throw new Error("LivePortrait 结果文件不可用");
  try {
    const info = await stat(task.resultPath);
    if (!info.isFile() || !info.size || info.size > MAX_VIDEO_BYTES) {
      throw new Error("LivePortrait 结果大小无效");
    }
    const bytes = new Uint8Array(await readFile(task.resultPath));
    if (!hasMatchingVideoSignature("video/mp4", bytes)) {
      throw new Error("LivePortrait 结果不是有效 MP4");
    }
    return { bytes, mediaType: "video/mp4", visualIdentityId: task.visualIdentityId };
  } finally {
    release();
  }
}

async function readBoundedBody(response: Response) {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_VIDEO_BYTES) {
    throw new Error("Provider 结果超过 50MB");
  }
  const reader = response.body!.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > MAX_VIDEO_BYTES) {
      await reader.cancel();
      throw new Error("Provider 结果超过 50MB");
    }
    chunks.push(value);
  }
  if (!length) throw new Error("Provider 返回了空视频");
  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

function identifyVideoType(header: string | null, bytes: Uint8Array) {
  const candidate = header?.split(";", 1)[0].trim().toLowerCase();
  const types = [candidate, "video/mp4", "video/webm", "video/quicktime"];
  for (const mediaType of types) {
    if (mediaType && hasMatchingVideoSignature(mediaType, bytes)) return mediaType;
  }
  throw new Error("Provider 结果不是支持的视频容器");
}
