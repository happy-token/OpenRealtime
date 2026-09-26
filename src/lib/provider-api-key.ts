import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import { ADMIN_SESSION_MAX_AGE_SECONDS } from "./admin-auth";
import { userFromRequest } from "./user-session";
import { loadPersonalKey } from "./user-provider-credentials";

export type UserKeyProvider = "anam" | "minimax";

const COOKIE_NAMES: Record<UserKeyProvider, string> = {
  anam: "openrealtime_anam_key",
  minimax: "openrealtime_minimax_key",
};

function encryptionKey(): Buffer | null {
  const secret = process.env.VOICEAGENT_ADMIN_SESSION_SECRET;
  return secret && secret.length >= 32
    ? createHash("sha256").update(secret).digest()
    : null;
}

export function providerKeyCookieName(provider: UserKeyProvider) {
  return COOKIE_NAMES[provider];
}

export function sealProviderKey(value: string): string {
  const key = encryptionKey();
  if (!key) throw new Error("用户 API Key 会话加密尚未配置");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const payload = JSON.stringify({ key: value, expiresAt: Date.now() + ADMIN_SESSION_MAX_AGE_SECONDS * 1000 });
  const encrypted = Buffer.concat([cipher.update(payload, "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), encrypted]).toString("base64url");
}

function unsealProviderKey(value: string): string | null {
  const key = encryptionKey();
  if (!key) return null;
  try {
    const bytes = Buffer.from(value, "base64url");
    if (bytes.length < 29) return null;
    const decipher = createDecipheriv("aes-256-gcm", key, bytes.subarray(0, 12));
    decipher.setAuthTag(bytes.subarray(12, 28));
    const payload: unknown = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString("utf8"));
    if (!payload || typeof payload !== "object") return null;
    const parsed = payload as { key?: unknown; expiresAt?: unknown };
    return typeof parsed.key === "string" && typeof parsed.expiresAt === "number" && Date.now() < parsed.expiresAt
      ? parsed.key : null;
  } catch {
    return null;
  }
}

export function providerApiKey(request: Request, provider: UserKeyProvider): string | undefined {
  const userKey = request.headers.get("cookie")?.split(";").map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE_NAMES[provider]}=`))
    ?.slice(COOKIE_NAMES[provider].length + 1);
  if (userKey !== undefined) return unsealProviderKey(userKey) || undefined;
  return (
    provider === "anam" ? process.env.ANAM_API_KEY?.trim() : process.env.MINIMAX_API_KEY?.trim()
  ) || undefined;
}

export async function resolveProviderApiKey(request: Request, provider: UserKeyProvider): Promise<string | undefined> {
  const user = await userFromRequest(request);
  if (user) {
    const personal = await loadPersonalKey(user, provider);
    return personal || (
      provider === "anam" ? process.env.ANAM_API_KEY?.trim() : process.env.MINIMAX_API_KEY?.trim()
    ) || undefined;
  }
  return providerApiKey(request, provider);
}

export function providerKeyFingerprint(key: string): string {
  return createHash("sha256").update(key).digest("hex");
}
