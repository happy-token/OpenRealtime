const ANAM_API_URL = "https://api.anam.ai";
const ANAM_TOKEN_TIMEOUT_MS = 12_000;

export interface AnamEnvironment {
  ANAM_API_KEY?: string;
  ANAM_AVATAR_ID?: string;
  ANAM_AVATAR_MODEL?: string;
}

export interface AnamSessionToken {
  sessionToken: string;
  avatarId: string;
  avatarModel: string;
}

export class AnamSessionError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AnamSessionError";
  }
}

interface AnamTokenResponse {
  sessionToken?: unknown;
  message?: unknown;
  error?: unknown;
}

export function anamSessionConfig(environment: AnamEnvironment) {
  const apiKey = environment.ANAM_API_KEY?.trim();
  const avatarId = environment.ANAM_AVATAR_ID?.trim();
  const avatarModel = environment.ANAM_AVATAR_MODEL?.trim() || "cara-4";
  if (!apiKey) throw new AnamSessionError("Anam 尚未配置 API Key", 503);
  if (!avatarId) {
    throw new AnamSessionError(
      "尚未选择 Anam 人物形象，请先配置 Avatar ID",
      503,
    );
  }
  return { apiKey, avatarId, avatarModel };
}

export async function createAnamSessionToken(
  environment: AnamEnvironment,
  fetcher: typeof fetch = fetch,
): Promise<AnamSessionToken> {
  const config = anamSessionConfig(environment);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ANAM_TOKEN_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(`${ANAM_API_URL}/v1/auth/session-token`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        personaConfig: {
          avatarId: config.avatarId,
          avatarModel: config.avatarModel,
          enableAudioPassthrough: true,
        },
      }),
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError"
      ? "Anam 会话创建超时"
      : "暂时无法连接 Anam";
    throw new AnamSessionError(message, 503);
  } finally {
    clearTimeout(timeout);
  }

  let payload: AnamTokenResponse;
  try {
    payload = await response.json() as AnamTokenResponse;
  } catch {
    throw new AnamSessionError("Anam 返回了无效响应", 502);
  }

  if (!response.ok) {
    const upstreamMessage = typeof payload.message === "string"
      ? payload.message
      : typeof payload.error === "string"
        ? payload.error
        : "";
    throw new AnamSessionError(
      response.status === 401 || response.status === 403
        ? "Anam API Key 无效或无权使用该 Avatar"
        : upstreamMessage || "Anam 会话创建失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }

  if (typeof payload.sessionToken !== "string" || !payload.sessionToken) {
    throw new AnamSessionError("Anam 响应缺少会话凭据", 502);
  }
  return {
    sessionToken: payload.sessionToken,
    avatarId: config.avatarId,
    avatarModel: config.avatarModel,
  };
}
