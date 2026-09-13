import { createHash, randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readOwnedAvatarImage } from "@/lib/avatar-catalog-repository";
import {
  isMiniMaxModelId,
  isVideoGenerationModelId,
  VIDEO_GENERATION_DEFAULT_MODEL,
  VIDEO_GENERATION_MODELS,
} from "@/lib/ltx-avatar-action";
import {
  createOrReuseLocalLtxTask,
  getLocalLtxSubmissionByRequestId,
  LtxTaskSubmissionPendingError,
} from "@/lib/ltx-task-coordinator";
import { LtxProviderError } from "@/lib/ltx-video";
import { prepareMiniMaxFrameImage } from "@/lib/minimax-frame-image";
import {
  MINIMAX_DURATIONS,
  MINIMAX_RATIOS,
  MINIMAX_RESOLUTIONS,
  validateMiniMaxVideoOptions,
  type MiniMaxDuration,
  type MiniMaxImageRole,
  type MiniMaxRatio,
  type MiniMaxReferenceVideo,
  type MiniMaxResolution,
} from "@/lib/minimax-video";
import {
  assertVideoGenerationModelConfigured,
  createImageToVideo,
  isVideoGenerationProviderError,
} from "@/lib/video-generation-provider";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取视频生成状态" }, 403);
  }
  const requestId = request.nextUrl.searchParams.get("request_id");
  if (requestId) {
    if (!validRequestId(requestId)) return json({ error: "生成请求 ID 无效" }, 400);
    const record = getLocalLtxSubmissionByRequestId(requestId);
    if (!record) return json({ error: "没有找到可恢复的生成任务" }, 404);
    return json({
      request_id: requestId,
      submission_state: record.state,
      task_id: record.task?.taskId,
      state: record.task?.state ?? (record.state === "submission_unknown" ? "failed" : "queueing"),
      model: record.model,
      created_at: record.createdAt,
      error: record.state === "submission_unknown"
        ? "上次付费任务的提交结果无法确认。为避免重复扣费，系统不会自动重试，请先核对服务商任务记录。"
        : record.error,
    });
  }
  if (process.env.NODE_ENV === "production") {
    return json({ ready: false, configured: hasAnyConfiguredProvider(), error: "生产付费视频生成将在 GPU 与持久化存储验收后启用" }, 503);
  }
  try {
    const configuredModels = VIDEO_GENERATION_MODELS
      .filter((model) => model.provider === "minimax" ? process.env.MINIMAX_API_KEY?.trim() : process.env.LTX_API_KEY?.trim())
      .map((model) => model.id);
    if (!configuredModels.length) throw new LtxProviderError("视频生成尚未配置 API Key", 503);
    return json({ ready: true, configured: true, default_model: VIDEO_GENERATION_DEFAULT_MODEL, configured_models: configuredModels });
  } catch (error) {
    const known = isVideoGenerationProviderError(error);
    return json({ ready: false, configured: false, error: known ? error.message : "视频生成状态检查失败" }, known ? error.status : 500);
  }
}

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源创建视频生成任务" }, 403);
  }
  if (process.env.NODE_ENV === "production") {
    return json({ error: "生产付费视频生成将在 GPU 与持久化存储验收后启用，生产环境禁止创建付费任务" }, 503);
  }
  try {
    const length = Number(request.headers.get("content-length"));
    if (!Number.isFinite(length) || length <= 0) throw new LtxProviderError("请求缺少有效的 Content-Length", 411);
    const multipart = request.headers.get("content-type")?.toLowerCase().startsWith("multipart/form-data") ?? false;
    if (length > (multipart ? 52 * 1024 * 1024 : 16 * 1024)) throw new LtxProviderError("视频生成任务参数过大", 413);
    const payload = await readGenerationPayload(request, multipart);
    const requestId = typeof payload.requestId === "string" ? payload.requestId : randomUUID();
    if (!validRequestId(requestId)) throw new LtxProviderError("生成请求 ID 无效", 400);
    if (typeof payload.avatarId !== "string") throw new LtxProviderError("avatar_id 无效", 400);
    if (typeof payload.prompt !== "string") throw new LtxProviderError("请填写动作提示词", 400);
    if (!isVideoGenerationModelId(payload.model)) throw new LtxProviderError("视频生成模型无效", 400);
    const model = payload.model;
    if (payload.creditsAccepted !== true) throw new LtxProviderError("请先确认本次生成会消耗所选模型的 API 额度", 400);
    if (payload.rightsConfirmed !== true) throw new LtxProviderError("请先确认数字人形象的使用权", 400);
    assertVideoGenerationModelConfigured(videoGenerationEnvironment(), model);
    const source = await readOwnedAvatarImage(payload.avatarId);
    if (!source) throw new LtxProviderError("找不到这个 Avatar", 404);
    const prompt = payload.prompt.trim();
    const miniMaxOptions = isMiniMaxModelId(model) ? miniMaxOptionsFromPayload(payload) : undefined;
    const generationSource = miniMaxOptions && miniMaxOptions.imageRole !== "reference_image"
      ? await prepareMiniMaxFrameImage(source.bytes, source.mediaType, miniMaxOptions.ratio)
      : { ...source, transformed: false as const };
    const imageDataUrl = `data:${generationSource.mediaType};base64,${Buffer.from(generationSource.bytes).toString("base64")}`;
    const provenance = {
      visualIdentityId: payload.avatarId,
      sourceSha256: createHash("sha256").update(source.bytes).digest("hex"),
      prompt,
      model,
      ratio: miniMaxOptions?.ratio,
      resolution: miniMaxOptions?.resolution,
      duration: miniMaxOptions?.duration,
      imageRole: miniMaxOptions?.imageRole,
      referenceVideoSha256: miniMaxOptions?.referenceVideo
        ? createHash("sha256").update(miniMaxOptions.referenceVideo.bytes).digest("hex")
        : undefined,
    };
    const { task, reused } = await createOrReuseLocalLtxTask(provenance, () => createImageToVideo(
      videoGenerationEnvironment(),
      { imageDataUrl, prompt, model, ...miniMaxOptions },
    ), { requestId });
    return json({
      request_id: requestId,
      submission_state: "active",
      task_id: task.taskId,
      state: task.state,
      model: task.model,
      created_at: task.createdAt,
      reused,
    }, 202);
  } catch (error) {
    if (error instanceof LtxTaskSubmissionPendingError) {
      return json({
        request_id: error.record.requestIds.at(-1),
        submission_state: error.record.state,
        state: error.record.state === "submission_unknown" ? "failed" : "queueing",
        error: error.message,
        reused: true,
      }, 202);
    }
    const known = isVideoGenerationProviderError(error);
    return json(
      { error: known ? error.message : "图生视频任务创建失败" },
      known ? error.status : 500,
    );
  }
}

type GenerationPayload = {
  avatarId?: unknown;
  prompt?: unknown;
  model?: unknown;
  creditsAccepted?: unknown;
  rightsConfirmed?: unknown;
  ratio?: unknown;
  resolution?: unknown;
  duration?: unknown;
  imageRole?: unknown;
  referenceVideo?: MiniMaxReferenceVideo;
  requestId?: unknown;
};

async function readGenerationPayload(request: NextRequest, multipart: boolean): Promise<GenerationPayload> {
  if (!multipart) return await request.json() as GenerationPayload;
  const form = await request.formData();
  const file = form.get("referenceVideo");
  let referenceVideo: MiniMaxReferenceVideo | undefined;
  if (file instanceof File && file.size > 0) {
    const mediaType = miniMaxVideoMediaType(file);
    if (!mediaType) {
      throw new LtxProviderError("参考视频仅支持 MP4 或 MOV", 400);
    }
    if (file.size > 50 * 1024 * 1024) throw new LtxProviderError("参考视频不能超过 50MB", 413);
    referenceVideo = {
      bytes: new Uint8Array(await file.arrayBuffer()),
      mediaType,
      filename: file.name,
    };
  }
  return {
    avatarId: form.get("avatarId"),
    requestId: form.get("requestId"),
    prompt: form.get("prompt"),
    model: form.get("model"),
    creditsAccepted: form.get("creditsAccepted") === "true",
    rightsConfirmed: form.get("rightsConfirmed") === "true",
    ratio: form.get("ratio"),
    resolution: form.get("resolution"),
    duration: form.get("duration"),
    imageRole: form.get("imageRole"),
    referenceVideo,
  };
}

function miniMaxVideoMediaType(file: File): "video/mp4" | "video/quicktime" | undefined {
  if (file.type === "video/mp4" || file.type === "video/quicktime") return file.type;
  const name = file.name.toLowerCase();
  if (!file.type && name.endsWith(".mp4")) return "video/mp4";
  if (!file.type && name.endsWith(".mov")) return "video/quicktime";
  return undefined;
}

function miniMaxOptionsFromPayload(payload: GenerationPayload) {
  if (!isMiniMaxModelId(payload.model)) throw new LtxProviderError("MiniMax 模型无效", 400);
  const ratio = (payload.ratio ?? "adaptive") as MiniMaxRatio;
  const resolution = (payload.resolution ?? "768P") as MiniMaxResolution;
  const durationValue = payload.duration ?? 6;
  const duration = (typeof durationValue === "string" ? Number(durationValue) : durationValue) as MiniMaxDuration;
  const imageRole = (payload.imageRole ?? (payload.referenceVideo ? "reference_image" : "first_and_last_frame")) as MiniMaxImageRole;
  if (!MINIMAX_RATIOS.includes(ratio) || !MINIMAX_RESOLUTIONS.includes(resolution) || !MINIMAX_DURATIONS.includes(duration)) {
    throw new LtxProviderError("MiniMax 生成参数无效", 400);
  }
  const options = { ratio, resolution, duration, imageRole, referenceVideo: payload.referenceVideo };
  validateMiniMaxVideoOptions({ model: payload.model, ...options });
  return options;
}

function videoGenerationEnvironment() {
  return {
    LTX_API_KEY: process.env.LTX_API_KEY,
    LTX_API_URL: process.env.LTX_API_URL,
    MINIMAX_API_KEY: process.env.MINIMAX_API_KEY,
    MINIMAX_API_URL: process.env.MINIMAX_API_URL,
    MINIMAX_UPLOAD_CACHE_PATH: process.env.MINIMAX_UPLOAD_CACHE_PATH,
  };
}

function validRequestId(value: string) {
  return /^[A-Za-z0-9_-]{16,128}$/.test(value);
}

function hasAnyConfiguredProvider() {
  return Boolean(process.env.LTX_API_KEY?.trim() || process.env.MINIMAX_API_KEY?.trim());
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}
