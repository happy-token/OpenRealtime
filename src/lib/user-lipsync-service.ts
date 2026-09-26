import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { isIP } from "node:net";
import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";

export type UserLipsyncService = { url: string; token: string };

function encryptionKey(): Buffer {
  const encoded = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded) throw new Error("用户凭据加密密钥尚未配置");
  const key = Buffer.from(encoded, "base64url");
  if (key.length !== 32 || key.toString("base64url") !== encoded.replace(/=+$/, "")) throw new Error("用户凭据加密密钥格式无效");
  return key;
}

function aad(user: WebUser): Buffer {
  return Buffer.from(JSON.stringify([user.issuer, user.subject, "lipsync-service"]));
}

export function sealLipsyncToken(user: WebUser, token: string): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(aad(user));
  return Buffer.concat([iv, cipher.update(token, "utf8"), cipher.final(), cipher.getAuthTag()]);
}

export function unsealLipsyncToken(user: WebUser, sealed: Buffer): string {
  if (sealed.length < 29) throw new Error("服务令牌数据无效");
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), sealed.subarray(0, 12));
  decipher.setAAD(aad(user));
  decipher.setAuthTag(sealed.subarray(-16));
  return Buffer.concat([decipher.update(sealed.subarray(12, -16)), decipher.final()]).toString("utf8");
}

export function normalizePersonalLipsyncUrl(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 2048 || value !== value.trim()) throw new Error("请输入有效的服务地址");
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("请输入有效的服务地址"); }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/"
    || isIP(url.hostname) || url.hostname === "localhost" || url.hostname.endsWith(".localhost") || url.hostname.endsWith(".local")) {
    throw new Error("口型服务必须使用 HTTPS 根地址，不含凭据或查询参数");
  }
  const allowed = (process.env.VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS ?? "")
    .split(",").map((item) => item.trim()).filter(Boolean);
  if (!allowed.includes(url.origin)) throw new Error("此口型服务域名尚未获得站点运营方允许");
  return url.origin;
}

export function normalizePersonalLipsyncToken(value: unknown): string {
  if (typeof value !== "string" || value.length > 512 || value !== value.trim() || /[\x00-\x1f\x7f]/.test(value)) throw new Error("服务令牌格式无效");
  return value;
}

export async function loadUserLipsyncService(user: WebUser): Promise<UserLipsyncService | null> {
  const result = await userDatabase().query<{ url: string; sealed_token: Buffer | null }>(
    `SELECT url, sealed_token FROM ${userTable("user_lipsync_services")} WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  );
  const row = result.rows[0];
  if (!row) return null;
  return { url: normalizePersonalLipsyncUrl(row.url), token: row.sealed_token ? unsealLipsyncToken(user, row.sealed_token) : "" };
}

export async function saveUserLipsyncService(user: WebUser, urlInput: unknown, tokenInput?: unknown): Promise<void> {
  const url = normalizePersonalLipsyncUrl(urlInput);
  const token = tokenInput === undefined ? undefined : normalizePersonalLipsyncToken(tokenInput);
  const existing = token === undefined ? await userDatabase().query<{ url: string; sealed_token: Buffer | null }>(
    `SELECT url, sealed_token FROM ${userTable("user_lipsync_services")} WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  ) : null;
  const old = existing?.rows[0];
  const effectiveToken = token ?? (old?.url === url && old.sealed_token ? unsealLipsyncToken(user, old.sealed_token) : "");
  await userDatabase().query(
    `INSERT INTO ${userTable("user_lipsync_services")} (issuer, subject, url, sealed_token)
     VALUES ($1, $2, $3, $4) ON CONFLICT (issuer, subject) DO UPDATE SET
     url = EXCLUDED.url, sealed_token = EXCLUDED.sealed_token, updated_at = now()`,
    [user.issuer, user.subject, url, effectiveToken ? sealLipsyncToken(user, effectiveToken) : null],
  );
}

export async function deleteUserLipsyncService(user: WebUser): Promise<void> {
  await userDatabase().query(
    `DELETE FROM ${userTable("user_lipsync_services")} WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  );
}

export async function probeUserLipsyncService(service: UserLipsyncService): Promise<boolean> {
  const url = normalizePersonalLipsyncUrl(service.url);
  const response = await fetch(`${url}/health`, {
    headers: service.token ? { Authorization: `Bearer ${service.token}` } : undefined,
    redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) return false;
  const data = await response.json() as { status?: unknown; model?: unknown };
  return data.status === "ok" && data.model === "lipforcing-14b";
}
