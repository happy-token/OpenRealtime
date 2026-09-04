const VIDU_API_URL = "https://api.vidu.com";
const VIDU_REQUEST_TIMEOUT_MS = 20_000;

export const VIDU_DEFAULT_MODEL = "viduq3-pro-fast";
export const VIDU_DEFAULT_DURATION_SECONDS = 5;
export const VIDU_DEFAULT_RESOLUTION = "720p";

export interface ViduEnvironment {
  VIDU_API_KEY?: string;
  VIDU_API_URL?: string;
}

export interface ViduGenerationRequest {
  imageDataUrl: string;
  prompt: string;
  offPeak: boolean;
}

export type ViduTaskState = "created" | "queueing" | "processing" | "success" | "failed";

export interface ViduGenerationTask {
  taskId: string;
  state: ViduTaskState;
  model: string;
  credits?: number;
  offPeak: boolean;
}

export interface ViduCreation {
  id: string;
  url: string;
  coverUrl?: string;
}

export interface ViduGenerationStatus {
  taskId: string;
  state: ViduTaskState;
  errorCode?: string;
  creations: ViduCreation[];
}

export class ViduProviderError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ViduProviderError";
  }
}

type JsonRecord = Record<string, unknown>;

export function viduConfig(environment: ViduEnvironment) {
  const apiKey = environment.VIDU_API_KEY?.trim();
  if (!apiKey) throw new ViduProviderError("Vidu 尚未配置 API Key", 503);
  return {
    apiKey,
    apiUrl: environment.VIDU_API_URL?.trim().replace(/\/$/, "") || VIDU_API_URL,
  };
}

export async function getViduCredits(
  environment: ViduEnvironment,
  fetcher: typeof fetch = fetch,
): Promise<number> {
  const payload = await requestViduJson(
    environment,
    "/ent/v2/credits?show_detail=false",
    {},
    fetcher,
  );
  const credits = parseViduCredits(payload);
  if (credits === undefined) {
    throw new ViduProviderError("Vidu 账户响应缺少可识别的额度字段", 502);
  }
  return credits;
}

export async function createViduImageToVideo(
  environment: ViduEnvironment,
  input: ViduGenerationRequest,
  fetcher: typeof fetch = fetch,
): Promise<ViduGenerationTask> {
  const imageDataUrl = validateImageDataUrl(input.imageDataUrl);
  const prompt = input.prompt.trim();
  if (!prompt) throw new ViduProviderError("请填写动作提示词", 400);
  if (prompt.length > 5_000) throw new ViduProviderError("动作提示词不能超过 5000 字符", 400);

  const payload = await requestViduJson(environment, "/ent/v2/img2video", {
    method: "POST",
    body: JSON.stringify({
      model: VIDU_DEFAULT_MODEL,
      images: [imageDataUrl],
      prompt,
      audio: false,
      duration: VIDU_DEFAULT_DURATION_SECONDS,
      resolution: VIDU_DEFAULT_RESOLUTION,
      off_peak: input.offPeak,
    }),
  }, fetcher);

  const taskId = stringField(payload, "task_id");
  const state = taskState(payload.state);
  if (!taskId || !state) throw new ViduProviderError("Vidu 创建任务响应无效", 502);
  return {
    taskId,
    state,
    model: typeof payload.model === "string" ? payload.model : VIDU_DEFAULT_MODEL,
    credits: typeof payload.credits === "number" ? payload.credits : undefined,
    offPeak: input.offPeak,
  };
}

export async function getViduGeneration(
  environment: ViduEnvironment,
  taskId: string,
  fetcher: typeof fetch = fetch,
): Promise<ViduGenerationStatus> {
  const safeTaskId = taskId.trim();
  if (!/^[A-Za-z0-9_-]{6,128}$/.test(safeTaskId)) {
    throw new ViduProviderError("Vidu 任务 ID 无效", 400);
  }
  const payload = await requestViduJson(
    environment,
    `/ent/v2/tasks/${encodeURIComponent(safeTaskId)}/creations`,
    {},
    fetcher,
  );
  const state = taskState(payload.state);
  if (!state) throw new ViduProviderError("Vidu 任务状态响应无效", 502);
  const rawCreations = Array.isArray(payload.creations) ? payload.creations : [];
  const creations = rawCreations.flatMap((item): ViduCreation[] => {
    if (!isRecord(item)) return [];
    const id = stringField(item, "id");
    const url = safeHttpsUrl(item.url);
    if (!id || !url) return [];
    const coverUrl = safeHttpsUrl(item.cover_url);
    return [{ id, url, ...(coverUrl ? { coverUrl } : {}) }];
  });
  return {
    taskId: safeTaskId,
    state,
    errorCode: typeof payload.err_code === "string" && payload.err_code
      ? payload.err_code
      : undefined,
    creations,
  };
}

async function requestViduJson(
  environment: ViduEnvironment,
  path: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<JsonRecord> {
  const config = viduConfig(environment);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), VIDU_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(`${config.apiUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Token ${config.apiKey}`,
        "Content-Type": "application/json",
        ...init.headers,
      },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError"
      ? "Vidu 请求超时"
      : "暂时无法连接 Vidu";
    throw new ViduProviderError(message, 503);
  } finally {
    clearTimeout(timeout);
  }

  const payload = await response.json().catch(() => null);
  if (!isRecord(payload)) throw new ViduProviderError("Vidu 返回了无效响应", 502);
  if (!response.ok) {
    throw new ViduProviderError(
      response.status === 401 || response.status === 403
        ? "Vidu API Key 无效或无权调用当前模型"
        : response.status === 429
          ? "Vidu 当前请求过多，请稍后重试"
          : payload.reason === "CreditInsufficient"
            ? "Vidu API credits 不足"
            : "Vidu 请求失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }
  return payload;
}

function validateImageDataUrl(value: string) {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match) throw new ViduProviderError("仅支持 PNG、JPEG 或 WebP 图片", 400);
  const encoded = match[2];
  const estimatedBytes = Math.floor(encoded.length * 0.75);
  if (estimatedBytes > 10 * 1024 * 1024) {
    throw new ViduProviderError("图片不能超过 10MB", 400);
  }
  return value;
}

function taskState(value: unknown): ViduTaskState | undefined {
  return value === "created" || value === "queueing" || value === "processing"
      || value === "success" || value === "failed"
    ? value
    : undefined;
}

function safeHttpsUrl(value: unknown) {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function stringField(value: JsonRecord, field: string) {
  return typeof value[field] === "string" && value[field] ? value[field] : undefined;
}

function parseViduCredits(payload: JsonRecord) {
  if (isFiniteNumber(payload.credits)) return payload.credits;

  for (const field of ["remaining_credits", "remains"] as const) {
    const value = payload[field];
    if (isFiniteNumber(value)) return value;
    if (Array.isArray(value)) return sumCreditRemains(value);
  }

  const general = payload.general_remains;
  const exclusive = payload.exclusive_remains;
  if (Array.isArray(general) || Array.isArray(exclusive)) {
    return sumCreditRemains(Array.isArray(general) ? general : [])
      + sumCreditRemains(Array.isArray(exclusive) ? exclusive : []);
  }
  return undefined;
}

function sumCreditRemains(items: unknown[]) {
  return items.reduce<number>((total, item) => {
    if (!isRecord(item) || !isFiniteNumber(item.credit_remain)) return total;
    return total + item.credit_remain;
  }, 0);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
