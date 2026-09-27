import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { userDatabase, userTable } from "./user-db";
import { normalizePersonalLipsyncToken, normalizePersonalLipsyncUrl } from "./user-lipsync-service";
import type { WebUser } from "./user-session";

export const PERSONAL_TALKING_KINDS = ["musetalk", "wav2lip"] as const;
export type PersonalTalkingKind = typeof PERSONAL_TALKING_KINDS[number];
export type PersonalTalkingConnection = { url: string; token: string };

export function isPersonalTalkingKind(value: unknown): value is PersonalTalkingKind {
  return typeof value === "string" && PERSONAL_TALKING_KINDS.includes(value as PersonalTalkingKind);
}

function encryptionKey(): Buffer {
  const encoded = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded) throw new Error("用户凭据加密密钥尚未配置");
  const key = Buffer.from(encoded, "base64url");
  if (key.length !== 32 || key.toString("base64url") !== encoded.replace(/=+$/, "")) throw new Error("用户凭据加密密钥格式无效");
  return key;
}

function aad(user: WebUser, kind: PersonalTalkingKind): Buffer {
  return Buffer.from(JSON.stringify([user.issuer, user.subject, "talking-model-service", kind]));
}

function seal(user: WebUser, kind: PersonalTalkingKind, token: string): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(aad(user, kind));
  return Buffer.concat([iv, cipher.update(token, "utf8"), cipher.final(), cipher.getAuthTag()]);
}

function unseal(user: WebUser, kind: PersonalTalkingKind, data: Buffer): string {
  if (data.length < 29) throw new Error("服务令牌数据无效");
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), data.subarray(0, 12));
  decipher.setAAD(aad(user, kind));
  decipher.setAuthTag(data.subarray(-16));
  return Buffer.concat([decipher.update(data.subarray(12, -16)), decipher.final()]).toString("utf8");
}

export async function listUserTalkingServices(user: WebUser): Promise<Record<PersonalTalkingKind, PersonalTalkingConnection | null>> {
  const result = await userDatabase().query<{ kind: string; url: string; sealed_token: Buffer | null }>(
    `SELECT kind, url, sealed_token FROM ${userTable("user_talking_model_services")} WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  );
  const services = { musetalk: null, wav2lip: null } as Record<PersonalTalkingKind, PersonalTalkingConnection | null>;
  for (const row of result.rows) {
    if (!isPersonalTalkingKind(row.kind)) continue;
    services[row.kind] = { url: normalizePersonalLipsyncUrl(row.url), token: row.sealed_token ? unseal(user, row.kind, row.sealed_token) : "" };
  }
  return services;
}

export async function loadUserTalkingService(user: WebUser, kind: PersonalTalkingKind): Promise<PersonalTalkingConnection | null> {
  const result = await userDatabase().query<{ url: string; sealed_token: Buffer | null }>(
    `SELECT url, sealed_token FROM ${userTable("user_talking_model_services")} WHERE issuer = $1 AND subject = $2 AND kind = $3`,
    [user.issuer, user.subject, kind],
  );
  const row = result.rows[0];
  return row ? { url: normalizePersonalLipsyncUrl(row.url), token: row.sealed_token ? unseal(user, kind, row.sealed_token) : "" } : null;
}

export async function saveUserTalkingService(user: WebUser, kind: PersonalTalkingKind, urlInput: unknown, tokenInput?: unknown): Promise<PersonalTalkingConnection> {
  const url = normalizePersonalLipsyncUrl(urlInput);
  const token = tokenInput === undefined ? undefined : normalizePersonalLipsyncToken(tokenInput);
  const old = token === undefined ? await loadUserTalkingService(user, kind) : null;
  const effectiveToken = token ?? (old?.url === url ? old.token : "");
  await userDatabase().query(
    `INSERT INTO ${userTable("user_talking_model_services")} (issuer, subject, kind, url, sealed_token)
     VALUES ($1, $2, $3, $4, $5) ON CONFLICT (issuer, subject, kind) DO UPDATE SET
     url = EXCLUDED.url, sealed_token = EXCLUDED.sealed_token, updated_at = now()`,
    [user.issuer, user.subject, kind, url, effectiveToken ? seal(user, kind, effectiveToken) : null],
  );
  return { url, token: effectiveToken };
}

export async function deleteUserTalkingService(user: WebUser, kind: PersonalTalkingKind): Promise<void> {
  await userDatabase().query(
    `DELETE FROM ${userTable("user_talking_model_services")} WHERE issuer = $1 AND subject = $2 AND kind = $3`,
    [user.issuer, user.subject, kind],
  );
}
