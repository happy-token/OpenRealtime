export interface AvatarEvaluationPreviewPolicy {
  enabled: boolean;
  localDevelopmentAccess: boolean;
}

type AvatarEvaluationPreviewEnv = {
  NODE_ENV?: string;
  AVATAR_EVALUATION_PREVIEW_ENABLED?: string;
  AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED?: string;
  AVATAR_EVALUATION_LOOPBACK_BOUND?: string;
};

const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function avatarEvaluationPreviewPolicyFromEnv(
  env: AvatarEvaluationPreviewEnv = process.env,
): AvatarEvaluationPreviewPolicy {
  const enabled = env.AVATAR_EVALUATION_PREVIEW_ENABLED === "true";
  return {
    enabled,
    localDevelopmentAccess: enabled
      && env.NODE_ENV === "development"
      && env.AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED === "true"
      && env.AVATAR_EVALUATION_LOOPBACK_BOUND === "true",
  };
}

export function isSameOriginAvatarPreviewRequest(request: Request): boolean {
  if (request.headers.get("sec-fetch-site") !== "same-origin") return false;
  const referer = request.headers.get("referer");
  if (!referer) return false;
  try {
    const requestUrl = new URL(request.url);
    const refererUrl = new URL(referer);
    return LOOPBACK_HOSTNAMES.has(requestUrl.hostname)
      && LOOPBACK_HOSTNAMES.has(refererUrl.hostname)
      && requestUrl.protocol === refererUrl.protocol
      && effectivePort(requestUrl) === effectivePort(refererUrl);
  } catch {
    return false;
  }
}

function effectivePort(url: URL): string {
  if (url.port) return url.port;
  return url.protocol === "https:" ? "443" : "80";
}
