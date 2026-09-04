const DEFAULT_HAPPYIMAGE_API_URL = "http://127.0.0.1:8000";
const MAX_POLL_ATTEMPTS = 120;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export interface HappyImageEnvironment {
  HAPPYIMAGE_API_URL?: string;
  HAPPYIMAGE_API_KEY?: string;
}

export class HappyImageAvatarError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "HappyImageAvatarError";
  }
}

export async function createHappyImageAvatar(
  environment: HappyImageEnvironment,
  input: { prompt: string },
  fetcher: typeof fetch = fetch,
  wait: (milliseconds: number) => Promise<void> = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
) {
  const apiKey = environment.HAPPYIMAGE_API_KEY?.trim();
  if (!apiKey) throw new HappyImageAvatarError("尚未关联 HappyImage 账户", 503);
  const prompt = input.prompt.trim();
  if (!prompt) throw new HappyImageAvatarError("请填写形象描述", 400);
  if (prompt.length > 4_000) throw new HappyImageAvatarError("形象描述不能超过 4000 字符", 400);
  const apiUrl = (environment.HAPPYIMAGE_API_URL?.trim() || DEFAULT_HAPPYIMAGE_API_URL).replace(/\/$/, "");
  const taskId = `openrealtime-avatar-${crypto.randomUUID()}`;
  let task = await requestJson(`${apiUrl}/api/image-tasks/generations`, apiKey, {
    method: "POST",
    body: JSON.stringify({
      client_task_id: taskId,
      prompt,
      model: "gpt-image-2",
      size: "1024x1024",
      quality: "auto",
    }),
  }, fetcher);

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    if (task.status === "success") break;
    if (task.status === "error") throw new HappyImageAvatarError(taskError(task), quotaStatus(task),);
    await wait(1_000);
    const catalog = await requestJson(
      `${apiUrl}/api/image-tasks?ids=${encodeURIComponent(taskId)}`,
      apiKey,
      { method: "GET" },
      fetcher,
    );
    const items = Array.isArray(catalog.items) ? catalog.items : [];
    task = isRecord(items[0]) ? items[0] : {};
  }

  if (task.status !== "success") throw new HappyImageAvatarError("HappyImage 生成仍在处理中，请稍后重试", 504);
  const data = Array.isArray(task.data) ? task.data : [];
  const imageUrl = isRecord(data[0]) && typeof data[0].url === "string" ? data[0].url : "";
  if (!imageUrl) throw new HappyImageAvatarError("HappyImage 没有返回图片", 502);
  const imageResponse = await fetcher(imageUrl, { cache: "no-store" });
  if (!imageResponse.ok) throw new HappyImageAvatarError("HappyImage 结果图片读取失败", 502);
  const contentLength = Number(imageResponse.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_IMAGE_BYTES) {
    throw new HappyImageAvatarError("HappyImage 结果图片超过 10MB", 413);
  }
  const mediaType = imageResponse.headers.get("content-type")?.split(";", 1)[0] || "image/png";
  if (!new Set(["image/png", "image/jpeg", "image/webp"]).has(mediaType)) {
    throw new HappyImageAvatarError("HappyImage 返回了不支持的图片格式", 502);
  }
  const bytes = Buffer.from(await imageResponse.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) throw new HappyImageAvatarError("HappyImage 结果图片大小无效", 502);
  return { imageUrl: `data:${mediaType};base64,${bytes.toString("base64")}`, taskId };
}

async function requestJson(
  url: string,
  apiKey: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetcher(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new HappyImageAvatarError("暂时无法连接 HappyImage", 503);
  }
  const payload = await response.json().catch(() => null);
  if (!isRecord(payload)) throw new HappyImageAvatarError("HappyImage 返回了无效响应", 502);
  if (!response.ok) {
    const message = providerMessage(payload);
    throw new HappyImageAvatarError(
      response.status === 401 || response.status === 403
        ? "HappyImage 账户关联已失效"
        : message || "HappyImage 请求失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }
  return payload;
}

function taskError(task: Record<string, unknown>) {
  const message = providerMessage(task);
  return message || "HappyImage 生成失败";
}

function quotaStatus(task: Record<string, unknown>) {
  return /quota|credit|balance|额度|余额|欠费/i.test(taskError(task)) ? 402 : 502;
}

function providerMessage(value: Record<string, unknown>) {
  if (typeof value.error === "string") return value.error;
  if (isRecord(value.error) && typeof value.error.message === "string") return value.error.message;
  if (isRecord(value.detail) && typeof value.detail.error === "string") return value.detail.error;
  return "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
