import {
  ANAM_AVATAR_NAME_REQUIREMENT,
  isValidAnamAvatarName,
} from "./anam-avatar-name";

const ANAM_API_URL = "https://api.anam.ai";
const ANAM_REQUEST_TIMEOUT_MS = 15_000;
const ANAM_AVATAR_PAGE_SIZE = 100;

export interface AnamAvatarEnvironment {
  ANAM_API_KEY?: string;
}

export type AnamHostedAvatarOrigin = "personal" | "official";

export interface AnamHostedAvatar {
  id: string;
  displayName: string;
  variantName: string;
  imageUrl: string;
  videoUrl: string | null;
  createdAt: string;
  updatedAt: string;
  origin: AnamHostedAvatarOrigin;
  availableVersions: string[];
  activeVersion: string;
  description: string;
  displayTags: string[];
  renderStyle: string;
}

export interface AnamAvatarCatalog {
  avatars: AnamHostedAvatar[];
  total: number;
}

export interface CreateAnamAvatarRequest {
  displayName: string;
  image: File;
  avatarModel?: string;
}

export interface UpdateAnamAvatarNameRequest {
  avatarId: string;
  displayName: string;
}

export class AnamAvatarError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AnamAvatarError";
  }
}

export async function listAnamAvatars(
  environment: AnamAvatarEnvironment,
  fetcher: typeof fetch = fetch,
): Promise<AnamAvatarCatalog> {
  const apiKey = requireApiKey(environment);
  const avatars: AnamHostedAvatar[] = [];
  let page = 1;
  let total = 0;
  let lastPage = 1;

  do {
    const payload = await requestJson(
      `${ANAM_API_URL}/v1/avatars?page=${page}&perPage=${ANAM_AVATAR_PAGE_SIZE}`,
      { headers: { Authorization: `Bearer ${apiKey}` }, cache: "no-store" },
      fetcher,
      "当前 Anam API Key 没有读取形象目录的权限",
    );
    if (!isRecord(payload) || !Array.isArray(payload.data) || !isRecord(payload.meta)) {
      throw new AnamAvatarError("Anam 返回了无效的形象目录", 502);
    }
    const normalized = payload.data.map(normalizeAvatar);
    if (normalized.some((avatar) => avatar === null)) {
      throw new AnamAvatarError("Anam 返回了无效的形象目录", 502);
    }
    avatars.push(...normalized as AnamHostedAvatar[]);
    total = positiveInteger(payload.meta.total) ?? avatars.length;
    lastPage = positiveInteger(payload.meta.lastPage) ?? page;
    page += 1;
  } while (page <= lastPage);

  return { avatars, total };
}

export async function createAnamAvatar(
  environment: AnamAvatarEnvironment,
  request: CreateAnamAvatarRequest,
  fetcher: typeof fetch = fetch,
): Promise<AnamHostedAvatar> {
  const apiKey = requireApiKey(environment);
  const displayName = request.displayName.trim();
  if (!isValidAnamAvatarName(displayName)) {
    throw new AnamAvatarError(ANAM_AVATAR_NAME_REQUIREMENT, 400);
  }
  const form = new FormData();
  form.set("displayName", displayName);
  form.set("imageFile", request.image);
  if (request.avatarModel?.trim()) form.set("avatarModel", request.avatarModel.trim());
  const payload = await requestJson(
    `${ANAM_API_URL}/v1/avatars`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
      body: form,
      cache: "no-store",
    },
    fetcher,
    "当前 Anam API Key 没有创建形象的权限",
  );
  const avatar = normalizeAvatar(payload);
  if (!avatar) throw new AnamAvatarError("Anam 返回了无效的形象信息", 502);
  return avatar;
}

export async function updateAnamAvatarName(
  environment: AnamAvatarEnvironment,
  request: UpdateAnamAvatarNameRequest,
  fetcher: typeof fetch = fetch,
): Promise<AnamHostedAvatar> {
  const apiKey = requireApiKey(environment);
  const avatarId = request.avatarId.trim();
  const displayName = request.displayName.trim();
  if (!avatarId || avatarId.length > 128) {
    throw new AnamAvatarError("Anam 形象 ID 无效", 400);
  }
  if (!displayName || displayName.length > 50) {
    throw new AnamAvatarError("Anam 形象名称不能为空且不能超过 50 个字符", 400);
  }
  const payload = await requestJson(
    `${ANAM_API_URL}/v1/avatars/${encodeURIComponent(avatarId)}`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ displayName }),
      cache: "no-store",
    },
    fetcher,
    "当前 Anam API Key 没有修改形象的权限",
  );
  const avatar = normalizeAvatar(payload);
  if (!avatar) throw new AnamAvatarError("Anam 返回了无效的形象信息", 502);
  return avatar;
}

function requireApiKey(environment: AnamAvatarEnvironment): string {
  const apiKey = environment.ANAM_API_KEY?.trim();
  if (!apiKey) throw new AnamAvatarError("Anam 尚未配置 API Key", 503);
  return apiKey;
}

async function requestJson(
  url: string,
  init: RequestInit,
  fetcher: typeof fetch,
  forbiddenMessage: string,
): Promise<unknown> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ANAM_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(url, { ...init, signal: controller.signal });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "AbortError";
    throw new AnamAvatarError(timedOut ? "Anam 请求超时" : "暂时无法连接 Anam", 503);
  } finally {
    clearTimeout(timeout);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AnamAvatarError("Anam 返回了无效响应", 502);
  }
  if (!response.ok) {
    throw new AnamAvatarError(
      response.status === 401
        ? "Anam API Key 无效"
        : response.status === 403
          ? forbiddenMessage
          : providerMessage(payload) || "Anam 形象服务请求失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }
  return payload;
}

function normalizeAvatar(value: unknown): AnamHostedAvatar | null {
  if (!isRecord(value)
    || typeof value.id !== "string"
    || typeof value.displayName !== "string"
    || typeof value.imageUrl !== "string"
    || typeof value.activeVersion !== "string"
    || !Array.isArray(value.availableVersions)
    || !value.availableVersions.every((version) => typeof version === "string")) return null;
  return {
    id: value.id,
    displayName: value.displayName,
    variantName: typeof value.variantName === "string" ? value.variantName : "",
    imageUrl: value.imageUrl,
    videoUrl: typeof value.videoUrl === "string" ? value.videoUrl : null,
    createdAt: typeof value.createdAt === "string" ? value.createdAt : "",
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
    origin: typeof value.createdByOrganizationId === "string" && value.createdByOrganizationId
      ? "personal"
      : "official",
    availableVersions: value.availableVersions,
    activeVersion: value.activeVersion,
    description: typeof value.description === "string" ? value.description : "",
    displayTags: Array.isArray(value.displayTags)
      ? value.displayTags.filter((tag): tag is string => typeof tag === "string")
      : [],
    renderStyle: typeof value.renderStyle === "string" ? value.renderStyle : "unknown",
  };
}

function providerMessage(value: unknown): string {
  if (!isRecord(value)) return "";
  if (typeof value.message === "string") return value.message;
  return typeof value.error === "string" ? value.error : "";
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}
