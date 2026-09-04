import { createHmac, timingSafeEqual } from "node:crypto";

export const ADMIN_SESSION_COOKIE = "voiceagent_admin_session";
export const ADMIN_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;

export interface AdminAuthConfig {
  username: string;
  password: string;
  sessionSecret: string;
}

export type AdminLoginDefaults = Pick<AdminAuthConfig, "username" | "password">;

interface TokenOptions {
  nowMs?: number;
  maxAgeSeconds?: number;
}

export function adminAuthConfigFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): AdminAuthConfig | null {
  const username = env.VOICEAGENT_ADMIN_USERNAME?.trim();
  const password = env.VOICEAGENT_ADMIN_PASSWORD;
  const sessionSecret = env.VOICEAGENT_ADMIN_SESSION_SECRET;
  if (!username || !password || !sessionSecret) return null;
  if (password.length < 12 || sessionSecret.length < 32) return null;
  return { username, password, sessionSecret };
}

export function adminLoginDefaultsFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): AdminLoginDefaults | null {
  if (env.VOICEAGENT_ADMIN_AUTOFILL !== "true") return null;
  if (env.NODE_ENV === "production") return null;
  const runtimeEnvironment = (env.VOICEAGENT_ENV ?? env.NODE_ENV ?? "production").trim().toLowerCase();
  if (!new Set(["development", "test", "local"]).has(runtimeEnvironment)) {
    return null;
  }
  const config = adminAuthConfigFromEnv(env);
  return config ? { username: config.username, password: config.password } : null;
}

export function verifyAdminCredentials(
  username: string,
  password: string,
  config: AdminAuthConfig,
): boolean {
  return safeEqual(username, config.username) && safeEqual(password, config.password);
}

export function createAdminSessionToken(
  config: AdminAuthConfig,
  options: TokenOptions = {},
): string {
  const nowMs = options.nowMs ?? Date.now();
  const maxAgeSeconds = options.maxAgeSeconds ?? ADMIN_SESSION_MAX_AGE_SECONDS;
  const payload = Buffer.from(JSON.stringify({
    username: config.username,
    expiresAt: nowMs + maxAgeSeconds * 1000,
  })).toString("base64url");
  return `${payload}.${signature(payload, config.sessionSecret)}`;
}

export function verifyAdminSessionToken(
  token: string | undefined,
  config: AdminAuthConfig,
  options: Pick<TokenOptions, "nowMs"> = {},
): { username: string } | null {
  if (!token) return null;
  const [payload, providedSignature, extra] = token.split(".");
  if (!payload || !providedSignature || extra) return null;
  if (!safeEqual(providedSignature, signature(payload, config.sessionSecret))) return null;
  try {
    const decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      username?: unknown;
      expiresAt?: unknown;
    };
    const nowMs = options.nowMs ?? Date.now();
    if (
      decoded.username !== config.username ||
      typeof decoded.expiresAt !== "number" ||
      !Number.isFinite(decoded.expiresAt) ||
      nowMs >= decoded.expiresAt
    ) return null;
    return { username: config.username };
  } catch {
    return null;
  }
}

function signature(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

function safeEqual(left: string, right: string): boolean {
  const leftDigest = createHmac("sha256", "voiceagent-admin-compare").update(left).digest();
  const rightDigest = createHmac("sha256", "voiceagent-admin-compare").update(right).digest();
  return timingSafeEqual(leftDigest, rightDigest);
}
