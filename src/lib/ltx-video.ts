import { isLtxModelId, type LtxModelId } from "./ltx-avatar-action";
import type {
  VideoGenerationStatus,
  VideoGenerationTask,
  VideoGenerationTaskState,
} from "./video-generation-types";

const LTX_API_URL = "https://api.ltx.io";
const LTX_REQUEST_TIMEOUT_MS = 20_000;

export interface LtxEnvironment {
  LTX_API_KEY?: string;
  LTX_API_URL?: string;
}

export type LtxTaskState = VideoGenerationTaskState;
export type LtxGenerationTask = VideoGenerationTask & { model: LtxModelId };
export type LtxGenerationStatus = VideoGenerationStatus;

export class LtxProviderError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "LtxProviderError";
  }
}

type JsonRecord = Record<string, unknown>;

export function ltxConfig(environment: LtxEnvironment) {
  const apiKey = environment.LTX_API_KEY?.trim();
  if (!apiKey) throw new LtxProviderError("LTX 尚未配置 API Key", 503);
  return {
    apiKey,
    apiUrl: environment.LTX_API_URL?.trim().replace(/\/$/, "") || LTX_API_URL,
  };
}

export async function createLtxImageToVideo(
  environment: LtxEnvironment,
  input: { imageDataUrl: string; prompt: string; model: LtxModelId },
  fetcher: typeof fetch = fetch,
): Promise<LtxGenerationTask> {
  const imageDataUrl = validateImageDataUrl(input.imageDataUrl);
  const prompt = input.prompt.trim();
  if (!prompt) throw new LtxProviderError("请填写动作提示词", 400);
  if (prompt.length > 5_000) throw new LtxProviderError("动作提示词不能超过 5000 字符", 400);
  if (!isLtxModelId(input.model)) throw new LtxProviderError("LTX 模型无效", 400);

  const payload = await requestLtxJson(environment, "/v2/image-to-video", {
    method: "POST",
    body: JSON.stringify({
      image_uri: imageDataUrl,
      last_frame_uri: imageDataUrl,
      prompt,
      model: input.model,
      duration: 6,
      resolution: "720x1280",
      fps: 25,
      generate_audio: false,
      camera_motion: "static",
    }),
  }, fetcher);
  const taskId = stringField(payload, "id");
  const createdAt = stringField(payload, "created_at");
  if (!taskId || !createdAt) throw new LtxProviderError("LTX 创建任务响应无效", 502);
  return { taskId, state: "queueing", model: input.model, createdAt };
}

export async function getLtxGeneration(
  environment: LtxEnvironment,
  taskId: string,
  fetcher: typeof fetch = fetch,
): Promise<LtxGenerationStatus> {
  const safeTaskId = taskId.trim();
  if (!/^[A-Za-z0-9_-]{6,128}$/.test(safeTaskId)) {
    throw new LtxProviderError("LTX 任务 ID 无效", 400);
  }
  const payload = await requestLtxJson(
    environment,
    `/v2/image-to-video/${encodeURIComponent(safeTaskId)}`,
    {},
    fetcher,
  );
  const responseTaskId = stringField(payload, "id");
  if (responseTaskId && responseTaskId !== safeTaskId) {
    throw new LtxProviderError("LTX 任务状态响应无效", 502);
  }
  const status = payload.status;
  if (status === "pending") return { taskId: safeTaskId, state: "queueing" };
  if (status === "processing") return { taskId: safeTaskId, state: "processing" };
  if (status === "failed") {
    const error = isRecord(payload.error) && typeof payload.error.message === "string"
      ? payload.error.message
      : "LTX 动作生成失败";
    return { taskId: safeTaskId, state: "failed", error };
  }
  if (status === "completed") {
    const videoUrl = isRecord(payload.result) ? safeHttpsUrl(payload.result.video_url) : undefined;
    if (!videoUrl) throw new LtxProviderError("LTX 成功响应缺少视频地址", 502);
    return { taskId: safeTaskId, state: "success", videoUrl };
  }
  throw new LtxProviderError("LTX 任务状态响应无效", 502);
}

async function requestLtxJson(
  environment: LtxEnvironment,
  path: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<JsonRecord> {
  const config = ltxConfig(environment);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), LTX_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(`${config.apiUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
        ...init.headers,
      },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError"
      ? "LTX 请求超时"
      : "暂时无法连接 LTX";
    throw new LtxProviderError(message, 503);
  } finally {
    clearTimeout(timeout);
  }
  const payload = await response.json().catch(() => null);
  if (!isRecord(payload)) throw new LtxProviderError("LTX 返回了无效响应", 502);
  if (!response.ok) {
    const message = isRecord(payload.error) && typeof payload.error.message === "string"
      ? payload.error.message
      : undefined;
    throw new LtxProviderError(
      response.status === 401 || response.status === 403
        ? "LTX API Key 无效或无权调用当前模型"
        : response.status === 402
          ? "LTX 账户余额不足"
          : response.status === 429
            ? "LTX 当前请求过多，请稍后重试"
            : message || "LTX 请求失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }
  return payload;
}

function validateImageDataUrl(value: string) {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match) throw new LtxProviderError("仅支持 PNG、JPEG 或 WebP 图片", 400);
  if (match[2].length > 7 * 1024 * 1024) {
    throw new LtxProviderError("LTX 图片编码后不能超过 7MB", 400);
  }
  return value;
}

function safeHttpsUrl(value: unknown) {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function stringField(value: JsonRecord, field: string) {
  return typeof value[field] === "string" && value[field] ? value[field] : undefined;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
