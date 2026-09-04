const LIVEAVATAR_API_URL = "https://api.liveavatar.com";
const LIVEAVATAR_TOKEN_TIMEOUT_MS = 12_000;

export interface LiveAvatarEnvironment {
  LIVEAVATAR_API_KEY?: string;
  LIVEAVATAR_AVATAR_ID?: string;
  LIVEAVATAR_SANDBOX?: string;
}

export interface LiveAvatarSessionToken {
  sessionToken: string;
  sessionId: string;
}

export class LiveAvatarSessionError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "LiveAvatarSessionError";
  }
}

interface LiveAvatarTokenResponse {
  data?: {
    session_token?: unknown;
    session_id?: unknown;
  };
}

export function liveAvatarSessionConfig(environment: LiveAvatarEnvironment) {
  const apiKey = environment.LIVEAVATAR_API_KEY?.trim();
  const sandbox = environment.LIVEAVATAR_SANDBOX?.trim().toLowerCase() !== "false";
  const avatarId = environment.LIVEAVATAR_AVATAR_ID?.trim();
  if (!apiKey) throw new LiveAvatarSessionError("LiveAvatar 尚未配置 API Key", 503);
  if (!avatarId) {
    throw new LiveAvatarSessionError(
      "尚未选择 HeyGen 人物形象，请先配置 Avatar ID",
      503,
    );
  }
  return {
    apiKey,
    avatarId,
    sandbox,
  };
}

export async function createLiveAvatarSessionToken(
  environment: LiveAvatarEnvironment,
  fetcher: typeof fetch = fetch,
): Promise<LiveAvatarSessionToken> {
  const config = liveAvatarSessionConfig(environment);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), LIVEAVATAR_TOKEN_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetcher(`${LIVEAVATAR_API_URL}/v1/sessions/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-KEY": config.apiKey,
      },
      body: JSON.stringify({
        mode: "LITE",
        avatar_id: config.avatarId,
        is_sandbox: config.sandbox,
      }),
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError"
      ? "LiveAvatar 会话创建超时"
      : "暂时无法连接 LiveAvatar";
    throw new LiveAvatarSessionError(message, 503);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new LiveAvatarSessionError(
      response.status === 401 || response.status === 403
        ? "LiveAvatar API Key 无效或无权使用该 Avatar"
        : "LiveAvatar 会话创建失败",
      response.status >= 400 && response.status < 500 ? response.status : 502,
    );
  }

  let payload: LiveAvatarTokenResponse;
  try {
    payload = await response.json() as LiveAvatarTokenResponse;
  } catch {
    throw new LiveAvatarSessionError("LiveAvatar 返回了无效响应", 502);
  }
  const sessionToken = payload.data?.session_token;
  const sessionId = payload.data?.session_id;
  if (typeof sessionToken !== "string" || !sessionToken || typeof sessionId !== "string") {
    throw new LiveAvatarSessionError("LiveAvatar 响应缺少会话凭据", 502);
  }
  return { sessionToken, sessionId };
}
