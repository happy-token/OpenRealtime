import {
  adminAuthConfigFromEnv,
  verifyAdminSessionToken,
} from "./admin-auth";

const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function canUseAvatarTestApis(
  request: Request,
  sessionToken?: string,
  environment: NodeJS.ProcessEnv = process.env,
): boolean {
  const adminConfig = adminAuthConfigFromEnv(environment);
  if (adminConfig && verifyAdminSessionToken(sessionToken, adminConfig)) return true;

  return environment.NODE_ENV === "development"
    && environment.AVATAR_LOCAL_TEST_MODE === "true"
    && environment.AVATAR_EVALUATION_LOOPBACK_BOUND === "true"
    && isSameOriginLoopbackRequest(request);
}

export function isSameOriginAvatarMutation(request: Request): boolean {
  const source = request.headers.get("origin") ?? request.headers.get("referer");
  if (!source) return false;
  try {
    const requestUrl = new URL(request.url);
    const allowedOrigins = new Set([requestUrl.origin]);
    const host = request.headers.get("host");
    if (host) allowedOrigins.add(new URL(`${requestUrl.protocol}//${host}`).origin);
    return allowedOrigins.has(new URL(source).origin);
  } catch {
    return false;
  }
}

function isSameOriginLoopbackRequest(request: Request): boolean {
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite && fetchSite !== "same-origin") return false;
  const source = request.headers.get("origin") ?? request.headers.get("referer");
  if (!source) return false;
  try {
    const requestUrl = new URL(request.url);
    const sourceUrl = new URL(source);
    return LOOPBACK_HOSTNAMES.has(requestUrl.hostname)
      && LOOPBACK_HOSTNAMES.has(sourceUrl.hostname)
      && requestUrl.protocol === sourceUrl.protocol
      && effectivePort(requestUrl) === effectivePort(sourceUrl);
  } catch {
    return false;
  }
}

function effectivePort(url: URL): string {
  if (url.port) return url.port;
  return url.protocol === "https:" ? "443" : "80";
}
