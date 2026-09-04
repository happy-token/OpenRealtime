import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import type { MiniMaxModelId } from "./ltx-avatar-action";
import {
  MINIMAX_DURATIONS,
  MINIMAX_RATIOS,
  MINIMAX_RESOLUTIONS,
  type MiniMaxDuration,
  type MiniMaxImageRole,
  type MiniMaxRatio,
  type MiniMaxResolution,
} from "./minimax-video-options";
import type { VideoGenerationStatus, VideoGenerationTask } from "./video-generation-types";

const MINIMAX_API_URL = "https://api.minimax.cn";
const MINIMAX_REQUEST_TIMEOUT_MS = 45_000;
const MINIMAX_FILE_CACHE_TTL_MS = (6 * 24 + 23) * 60 * 60 * 1_000;
const MAX_UPLOAD_BYTES: Record<MiniMaxGenerationMediaType, number> = {
  "image/jpeg": 30 * 1024 * 1024, "image/png": 30 * 1024 * 1024,
  "image/webp": 30 * 1024 * 1024, "image/heic": 30 * 1024 * 1024,
  "image/heif": 30 * 1024 * 1024, "video/mp4": 50 * 1024 * 1024,
  "video/quicktime": 50 * 1024 * 1024, "audio/wav": 15 * 1024 * 1024,
  "audio/mpeg": 15 * 1024 * 1024,
};

export { MINIMAX_DURATIONS, MINIMAX_RATIOS, MINIMAX_RESOLUTIONS } from "./minimax-video-options";
export type { MiniMaxDuration, MiniMaxImageRole, MiniMaxRatio, MiniMaxResolution } from "./minimax-video-options";

export interface MiniMaxEnvironment {
  MINIMAX_API_KEY?: string;
  MINIMAX_API_URL?: string;
  MINIMAX_UPLOAD_CACHE_PATH?: string;
}
export type MiniMaxGenerationMediaType =
  | "image/jpeg" | "image/png" | "image/webp" | "image/heic" | "image/heif"
  | "video/mp4" | "video/quicktime" | "audio/wav" | "audio/mpeg";
export type MiniMaxReferenceVideo = {
  bytes: Uint8Array;
  mediaType: "video/mp4" | "video/quicktime";
  filename: string;
};
export type MiniMaxVideoInput = {
  imageDataUrl: string;
  prompt: string;
  model: MiniMaxModelId;
  ratio: MiniMaxRatio;
  resolution: MiniMaxResolution;
  duration: MiniMaxDuration;
  imageRole: MiniMaxImageRole;
  referenceVideo?: MiniMaxReferenceVideo;
};

export class MiniMaxProviderError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "MiniMaxProviderError";
  }
}

type JsonRecord = Record<string, unknown>;
type MiniMaxContentItem =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string }; role: "first_frame" | "last_frame" | "reference_image" }
  | { type: "video_url"; video_url: { url: string }; role: "reference_video" };
type UploadCacheEntry = { fileId: string; uri: `mm_file://${string}`; expiresAt: number };
type UploadCacheStore = {
  completed: Map<string, UploadCacheEntry>;
  pending: Map<string, Promise<UploadCacheEntry>>;
};
type ContextWorkflow = {
  content: MiniMaxContentItem[];
  ratio: MiniMaxRatio;
  resolution: MiniMaxResolution;
  duration: MiniMaxDuration;
  generationTaskId?: string;
  generationPromise?: Promise<string>;
};

const globalMiniMax = globalThis as typeof globalThis & {
  __openrealtimeMiniMaxUploadCache?: UploadCacheStore;
  __openrealtimeMiniMaxContextWorkflows?: Map<string, ContextWorkflow>;
  __openrealtimeMiniMaxCacheLoads?: Map<string, Promise<void>>;
  __openrealtimeMiniMaxCacheWrites?: Map<string, Promise<void>>;
};
const uploadCache: UploadCacheStore = globalMiniMax.__openrealtimeMiniMaxUploadCache ??= {
  completed: new Map(), pending: new Map(),
};
const contextWorkflows: Map<string, ContextWorkflow> = globalMiniMax.__openrealtimeMiniMaxContextWorkflows ??= new Map<string, ContextWorkflow>();
const cacheLoads = globalMiniMax.__openrealtimeMiniMaxCacheLoads ??= new Map<string, Promise<void>>();
const cacheWrites = globalMiniMax.__openrealtimeMiniMaxCacheWrites ??= new Map<string, Promise<void>>();

export function miniMaxConfig(environment: MiniMaxEnvironment) {
  const apiKey = environment.MINIMAX_API_KEY?.trim();
  if (!apiKey) throw new MiniMaxProviderError("MiniMax 尚未配置 API Key", 503);
  return { apiKey, apiUrl: environment.MINIMAX_API_URL?.trim().replace(/\/$/, "") || MINIMAX_API_URL };
}

export function validateMiniMaxVideoOptions(input: Pick<MiniMaxVideoInput, "model" | "ratio" | "resolution" | "duration" | "imageRole" | "referenceVideo">) {
  if (!MINIMAX_RATIOS.includes(input.ratio)) throw new MiniMaxProviderError("MiniMax 画面比例无效", 400);
  if (!MINIMAX_RESOLUTIONS.includes(input.resolution)) throw new MiniMaxProviderError("MiniMax 分辨率无效", 400);
  if (!MINIMAX_DURATIONS.includes(input.duration)) throw new MiniMaxProviderError("MiniMax 视频时长无效", 400);
  if (!["first_and_last_frame", "first_frame", "last_frame", "reference_image"].includes(input.imageRole)) {
    throw new MiniMaxProviderError("MiniMax 数字人形象角色无效", 400);
  }
  if (input.referenceVideo && input.imageRole !== "reference_image") {
    throw new MiniMaxProviderError("参考视频不能和首帧或尾帧同时使用，请将形象角色设为多模态参考图", 400);
  }
  if (input.model === "MiniMax-H3-Max") {
    if (input.resolution === "2K") throw new MiniMaxProviderError("H3 Max 暂不支持 2K", 400);
    if (input.duration < 5) throw new MiniMaxProviderError("H3 Max 最短生成 5 秒", 400);
    if (input.imageRole === "reference_image") throw new MiniMaxProviderError("H3 Max 不支持多模态参考图，请改用 H3", 400);
    if (input.referenceVideo) throw new MiniMaxProviderError("H3 Max 不支持参考视频，请改用 H3", 400);
  } else if (input.resolution === "480P") {
    throw new MiniMaxProviderError("H3 仅支持 768P 或 2K", 400);
  }
}

export async function uploadMiniMaxGenerationInput(
  environment: MiniMaxEnvironment,
  input: { bytes: Uint8Array; mediaType: MiniMaxGenerationMediaType; filename: string },
  fetcher: typeof fetch = fetch,
) {
  const limit = MAX_UPLOAD_BYTES[input.mediaType];
  if (!limit || !input.bytes.byteLength || input.bytes.byteLength > limit) {
    throw new MiniMaxProviderError("MiniMax 输入素材格式或大小无效", 400);
  }
  const config = miniMaxConfig(environment);
  const cachePath = miniMaxUploadCachePath(environment);
  if (cachePath) await loadPersistentUploadCache(cachePath);
  pruneUploadCache();
  const accountHash = createHash("sha256").update(`${config.apiUrl}\0${config.apiKey}`).digest("hex");
  const contentHash = createHash("sha256").update(input.bytes).digest("hex");
  const key = `${accountHash}:${input.mediaType}:${contentHash}`;
  const cached = uploadCache.completed.get(key);
  if (cached) return { fileId: cached.fileId, uri: cached.uri, reused: true, contentHash };
  const inflight = uploadCache.pending.get(key);
  if (inflight) {
    const uploaded = await inflight;
    return { fileId: uploaded.fileId, uri: uploaded.uri, reused: true, contentHash };
  }
  const pending = uploadMiniMaxGenerationInputUncached(environment, input, fetcher);
  uploadCache.pending.set(key, pending);
  try {
    const uploaded = await pending;
    uploadCache.completed.set(key, uploaded);
    if (cachePath) await persistUploadCache(cachePath).catch((error) => {
      console.warn("Failed to persist MiniMax upload deduplication index", error);
    });
    return { fileId: uploaded.fileId, uri: uploaded.uri, reused: false, contentHash };
  } finally {
    if (uploadCache.pending.get(key) === pending) uploadCache.pending.delete(key);
  }
}

export async function createMiniMaxImageToVideo(
  environment: MiniMaxEnvironment,
  input: MiniMaxVideoInput,
  fetcher: typeof fetch = fetch,
): Promise<VideoGenerationTask> {
  validateMiniMaxVideoOptions(input);
  const prompt = validatePrompt(input.prompt);
  const content = await buildGenerationContent(environment, { ...input, prompt }, fetcher);
  if (input.model === "MiniMax-H3-Context-IR") {
    const payload = await requestMiniMaxJson(environment, "/v2/h3_context_ir", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "MiniMax-H3", content, duration: input.duration, ratio: input.ratio }),
    }, fetcher);
    const taskId = requiredTaskId(payload, "MiniMax Context IR 创建任务响应无效");
    contextWorkflows.set(taskId, { content, ratio: input.ratio, resolution: input.resolution, duration: input.duration });
    return generationTask(taskId, input.model);
  }
  const taskId = await createDirectGeneration(environment, {
    model: input.model, content, ratio: input.ratio, resolution: input.resolution, duration: input.duration,
  }, fetcher);
  return generationTask(taskId, input.model);
}

export async function getMiniMaxGeneration(
  environment: MiniMaxEnvironment,
  taskId: string,
  model: MiniMaxModelId,
  fetcher: typeof fetch = fetch,
): Promise<VideoGenerationStatus> {
  const safeTaskId = validateTaskId(taskId);
  if (model !== "MiniMax-H3-Context-IR") {
    return mapVideoGenerationTask(safeTaskId, await queryMiniMaxTask(environment, safeTaskId, fetcher));
  }
  const workflow = contextWorkflows.get(safeTaskId);
  if (!workflow) throw new MiniMaxProviderError("H3 Context IR 工作流已过期，请重新创建", 410);
  if (workflow.generationTaskId) {
    return mapVideoGenerationTask(safeTaskId, await queryMiniMaxTask(environment, workflow.generationTaskId, fetcher));
  }
  const contextTask = await queryMiniMaxTask(environment, safeTaskId, fetcher);
  if (contextTask.status === "queued") return { taskId: safeTaskId, state: "queueing" };
  if (contextTask.status === "running") return { taskId: safeTaskId, state: "processing" };
  if (contextTask.status === "failed" || contextTask.status === "cancelled") return failedStatus(safeTaskId, contextTask);
  if (contextTask.status !== "succeeded") throw new MiniMaxProviderError("MiniMax 任务状态响应无效", 502);
  const enhancedPrompt = isRecord(contextTask.content) && typeof contextTask.content.prompt === "string"
    ? validatePrompt(contextTask.content.prompt) : undefined;
  if (!enhancedPrompt) throw new MiniMaxProviderError("H3 Context IR 成功响应缺少增强提示词", 502);
  const enhancedContent = workflow.content.map((item) => item.type === "text"
    ? { type: "text", text: enhancedPrompt } as const : item);
  workflow.generationPromise ??= createDirectGeneration(environment, {
    model: "MiniMax-H3", content: enhancedContent, ratio: workflow.ratio,
    resolution: workflow.resolution, duration: workflow.duration,
  }, fetcher);
  try {
    workflow.generationTaskId = await workflow.generationPromise;
  } finally {
    workflow.generationPromise = undefined;
  }
  return { taskId: safeTaskId, state: "queueing" };
}

export function resetMiniMaxCachesForTest() {
  uploadCache.completed.clear();
  uploadCache.pending.clear();
  contextWorkflows.clear();
  cacheLoads.clear();
  cacheWrites.clear();
}

async function buildGenerationContent(
  environment: MiniMaxEnvironment,
  input: MiniMaxVideoInput & { prompt: string },
  fetcher: typeof fetch,
): Promise<MiniMaxContentItem[]> {
  const image = decodeImageDataUrl(input.imageDataUrl);
  const uploadedImage = await uploadMiniMaxGenerationInput(environment, {
    bytes: image.bytes, mediaType: image.mediaType,
    filename: `avatar-source.${extensionForMediaType(image.mediaType)}`,
  }, fetcher);
  const imageUrl = { url: uploadedImage.uri };
  const content: MiniMaxContentItem[] = [{ type: "text", text: input.prompt }];
  if (input.imageRole === "first_and_last_frame") content.push(
    { type: "image_url", image_url: imageUrl, role: "first_frame" },
    { type: "image_url", image_url: imageUrl, role: "last_frame" },
  );
  else content.push({ type: "image_url", image_url: imageUrl, role: input.imageRole });
  if (input.referenceVideo) {
    const uploadedVideo = await uploadMiniMaxGenerationInput(environment, input.referenceVideo, fetcher);
    content.push({ type: "video_url", video_url: { url: uploadedVideo.uri }, role: "reference_video" });
  }
  return content;
}

async function uploadMiniMaxGenerationInputUncached(
  environment: MiniMaxEnvironment,
  input: { bytes: Uint8Array; mediaType: MiniMaxGenerationMediaType; filename: string },
  fetcher: typeof fetch,
): Promise<UploadCacheEntry> {
  const form = new FormData();
  form.set("purpose", "video_generation_input");
  form.set("file", new File([input.bytes.slice().buffer], safeFilename(input.filename, input.mediaType), { type: input.mediaType }));
  const payload = await requestMiniMaxJson(environment, "/v1/files/upload", { method: "POST", body: form }, fetcher);
  const file = isRecord(payload.file) ? payload.file : undefined;
  const fileId = stringOrNumberField(file, "file_id");
  if (!fileId) throw new MiniMaxProviderError("MiniMax 文件上传响应无效", 502);
  return { fileId, uri: `mm_file://${fileId}`, expiresAt: Date.now() + MINIMAX_FILE_CACHE_TTL_MS };
}

async function createDirectGeneration(
  environment: MiniMaxEnvironment,
  input: { model: "MiniMax-H3" | "MiniMax-H3-Max"; content: MiniMaxContentItem[]; ratio: MiniMaxRatio; resolution: MiniMaxResolution; duration: MiniMaxDuration },
  fetcher: typeof fetch,
) {
  const payload = await requestMiniMaxJson(environment, "/v2/video_generation", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, aigc_watermark: false }),
  }, fetcher);
  return requiredTaskId(payload, "MiniMax 创建任务响应无效");
}

async function queryMiniMaxTask(environment: MiniMaxEnvironment, taskId: string, fetcher: typeof fetch) {
  const payload = await requestMiniMaxJson(environment, `/v2/query/video_generation/${encodeURIComponent(taskId)}`, {}, fetcher);
  const task = isRecord(payload.task) ? payload.task : undefined;
  if (!task || stringOrNumberField(task, "id") !== taskId || typeof task.status !== "string") {
    throw new MiniMaxProviderError("MiniMax 任务状态响应无效", 502);
  }
  return task;
}

function mapVideoGenerationTask(publicTaskId: string, task: JsonRecord): VideoGenerationStatus {
  if (task.status === "queued") return { taskId: publicTaskId, state: "queueing" };
  if (task.status === "running") return { taskId: publicTaskId, state: "processing" };
  if (task.status === "failed" || task.status === "cancelled") return failedStatus(publicTaskId, task);
  if (task.status === "succeeded") {
    const videoUrl = isRecord(task.content) ? safeHttpsUrl(task.content.url) : undefined;
    if (!videoUrl) throw new MiniMaxProviderError("MiniMax 成功响应缺少视频地址", 502);
    return { taskId: publicTaskId, state: "success", videoUrl };
  }
  throw new MiniMaxProviderError("MiniMax 任务状态响应无效", 502);
}

function failedStatus(taskId: string, task: JsonRecord): VideoGenerationStatus {
  const error = isRecord(task.error) && typeof task.error.message === "string"
    ? task.error.message : task.status === "cancelled" ? "MiniMax 动作生成已取消" : "MiniMax 动作生成失败";
  return { taskId, state: "failed", error };
}

async function requestMiniMaxJson(environment: MiniMaxEnvironment, path: string, init: RequestInit, fetcher: typeof fetch): Promise<JsonRecord> {
  const config = miniMaxConfig(environment);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), MINIMAX_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(`${config.apiUrl}${path}`, {
      ...init, headers: { Authorization: `Bearer ${config.apiKey}`, ...init.headers },
      cache: "no-store", signal: controller.signal,
    });
  } catch (error) {
    throw new MiniMaxProviderError(error instanceof Error && error.name === "AbortError" ? "MiniMax 请求超时" : "暂时无法连接 MiniMax", 503);
  } finally {
    clearTimeout(timeout);
  }
  const payload = await response.json().catch(() => null);
  if (!isRecord(payload)) throw new MiniMaxProviderError("MiniMax 返回了无效响应", 502);
  const baseCode = isRecord(payload.base_resp) && typeof payload.base_resp.status_code === "number" ? payload.base_resp.status_code : 0;
  if (!response.ok || baseCode !== 0) {
    const providerMessage = isRecord(payload.error) && typeof payload.error.message === "string"
      ? payload.error.message : isRecord(payload.base_resp) && typeof payload.base_resp.status_msg === "string" ? payload.base_resp.status_msg : undefined;
    throw new MiniMaxProviderError(
      response.status === 401 || response.status === 403 || baseCode === 1004 ? "MiniMax API Key 无效或无权调用当前模型"
        : response.status === 402 || baseCode === 1008 ? "MiniMax 账户余额不足"
          : response.status === 429 || baseCode === 1002 ? "MiniMax 当前请求过多，请稍后重试"
            : providerMessage || "MiniMax 请求失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }
  return payload;
}

function generationTask(taskId: string, model: MiniMaxModelId): VideoGenerationTask {
  return { taskId, state: "queueing", model, createdAt: new Date().toISOString() };
}
function validatePrompt(value: string) {
  const prompt = value.trim();
  if (!prompt) throw new MiniMaxProviderError("请填写动作提示词", 400);
  if (prompt.length > 7_000) throw new MiniMaxProviderError("动作提示词不能超过 7000 字符", 400);
  return prompt;
}
function validateTaskId(taskId: string) {
  const safeTaskId = taskId.trim();
  if (!/^[A-Za-z0-9_-]{6,128}$/.test(safeTaskId)) throw new MiniMaxProviderError("MiniMax 任务 ID 无效", 400);
  return safeTaskId;
}
function requiredTaskId(payload: JsonRecord, message: string) {
  const taskId = stringOrNumberField(payload, "task_id");
  if (!taskId) throw new MiniMaxProviderError(message, 502);
  return taskId;
}
function pruneUploadCache() {
  const now = Date.now();
  for (const [key, entry] of uploadCache.completed) if (entry.expiresAt <= now) uploadCache.completed.delete(key);
}
function miniMaxUploadCachePath(environment: MiniMaxEnvironment) {
  if (environment.MINIMAX_UPLOAD_CACHE_PATH === "") return undefined;
  return path.resolve(environment.MINIMAX_UPLOAD_CACHE_PATH || path.join(process.cwd(), ".openrealtime", "minimax-upload-cache.json"));
}
async function loadPersistentUploadCache(cachePath: string) {
  let load = cacheLoads.get(cachePath);
  if (!load) {
    load = readFile(cachePath, "utf8").then((value) => {
      const parsed = JSON.parse(value) as { entries?: Array<[string, UploadCacheEntry]> };
      for (const [key, entry] of parsed.entries ?? []) {
        if (typeof key === "string" && validUploadCacheEntry(entry) && entry.expiresAt > Date.now()) {
          uploadCache.completed.set(key, entry);
        }
      }
    }).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error;
    });
    cacheLoads.set(cachePath, load);
  }
  await load;
}
async function persistUploadCache(cachePath: string) {
  const previous = cacheWrites.get(cachePath) ?? Promise.resolve();
  const current = previous.catch(() => undefined).then(async () => {
    pruneUploadCache();
    await mkdir(path.dirname(cachePath), { recursive: true, mode: 0o700 });
    const temporaryPath = `${cachePath}.${process.pid}.tmp`;
    await writeFile(temporaryPath, JSON.stringify({ version: 1, entries: [...uploadCache.completed] }), { mode: 0o600 });
    await rename(temporaryPath, cachePath);
  });
  cacheWrites.set(cachePath, current);
  try { await current; }
  finally { if (cacheWrites.get(cachePath) === current) cacheWrites.delete(cachePath); }
}
function validUploadCacheEntry(value: unknown): value is UploadCacheEntry {
  if (!isRecord(value)) return false;
  return typeof value.fileId === "string"
    && typeof value.uri === "string"
    && value.uri === `mm_file://${value.fileId}`
    && typeof value.expiresAt === "number"
    && Number.isFinite(value.expiresAt);
}
function decodeImageDataUrl(value: string): { bytes: Uint8Array; mediaType: Extract<MiniMaxGenerationMediaType, `image/${string}`> } {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match) throw new MiniMaxProviderError("仅支持 PNG、JPEG 或 WebP 图片", 400);
  const mediaType = match[1] as Extract<MiniMaxGenerationMediaType, `image/${string}`>;
  const bytes = Uint8Array.from(Buffer.from(match[2], "base64"));
  if (!bytes.byteLength || bytes.byteLength > MAX_UPLOAD_BYTES[mediaType]) throw new MiniMaxProviderError("MiniMax 图片不能超过 30MB", 400);
  return { bytes, mediaType };
}
function safeFilename(value: string, mediaType: MiniMaxGenerationMediaType) {
  return value.trim().replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 100) || `generation-input.${extensionForMediaType(mediaType)}`;
}
function extensionForMediaType(mediaType: MiniMaxGenerationMediaType) {
  return ({ "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif", "video/mp4": "mp4", "video/quicktime": "mov", "audio/wav": "wav", "audio/mpeg": "mp3" } as const)[mediaType];
}
function safeHttpsUrl(value: unknown) {
  if (typeof value !== "string") return undefined;
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.toString() : undefined; }
  catch { return undefined; }
}
function stringOrNumberField(value: JsonRecord | undefined, field: string) {
  const candidate = value?.[field];
  return typeof candidate === "string" && candidate ? candidate
    : typeof candidate === "number" && Number.isSafeInteger(candidate) && candidate >= 0 ? String(candidate) : undefined;
}
function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
