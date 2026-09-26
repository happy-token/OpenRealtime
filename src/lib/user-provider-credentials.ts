import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";

export const PERSONAL_KEY_PROVIDERS = ["anam", "minimax", "doubao", "bella", "dashscope", "deepseek", "openai"] as const;
export type PersonalKeyProvider = typeof PERSONAL_KEY_PROVIDERS[number];

export interface PersonalKeyStatus {
  provider: PersonalKeyProvider;
  configured: boolean;
  suffix?: string;
  updatedAt?: string;
}

function encryptionKey(): Buffer {
  const encoded = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded) throw new Error("用户 API Key 加密密钥尚未配置");
  const bytes = Buffer.from(encoded, "base64url");
  if (bytes.length !== 32 || bytes.toString("base64url") !== encoded.replace(/=+$/, "")) {
    throw new Error("用户 API Key 加密密钥格式无效");
  }
  return bytes;
}

function associatedData(user: WebUser, provider: PersonalKeyProvider): Buffer {
  return Buffer.from(JSON.stringify([user.issuer, user.subject, provider]));
}

export function sealPersonalKey(user: WebUser, provider: PersonalKeyProvider, value: string): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(associatedData(user, provider));
  return Buffer.concat([iv, cipher.update(value, "utf8"), cipher.final(), cipher.getAuthTag()]);
}

export function unsealPersonalKey(user: WebUser, provider: PersonalKeyProvider, sealed: Buffer): string {
  if (sealed.length < 29) throw new Error("用户 API Key 数据无效");
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), sealed.subarray(0, 12));
  decipher.setAAD(associatedData(user, provider));
  decipher.setAuthTag(sealed.subarray(-16));
  return Buffer.concat([decipher.update(sealed.subarray(12, -16)), decipher.final()]).toString("utf8");
}

export function parsePersonalKeyProvider(value: unknown): PersonalKeyProvider | null {
  return typeof value === "string" && PERSONAL_KEY_PROVIDERS.includes(value as PersonalKeyProvider)
    ? value as PersonalKeyProvider : null;
}

export async function listPersonalKeyStatuses(user: WebUser): Promise<PersonalKeyStatus[]> {
  const result = await userDatabase().query<{ provider: string; suffix: string; updated_at: Date }>(
    `SELECT provider, suffix, updated_at FROM ${userTable("user_provider_credentials")}
     WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  );
  const byProvider = new Map(result.rows.map((row) => [row.provider, row]));
  return PERSONAL_KEY_PROVIDERS.map((provider) => {
    const row = byProvider.get(provider);
    return row
      ? { provider, configured: true, suffix: row.suffix, updatedAt: row.updated_at.toISOString() }
      : { provider, configured: false };
  });
}

export async function loadPersonalKey(user: WebUser, provider: PersonalKeyProvider): Promise<string | null> {
  const result = await userDatabase().query<{ sealed_key: Buffer }>(
    `SELECT sealed_key FROM ${userTable("user_provider_credentials")}
     WHERE issuer = $1 AND subject = $2 AND provider = $3`,
    [user.issuer, user.subject, provider],
  );
  return result.rows[0] ? unsealPersonalKey(user, provider, result.rows[0].sealed_key) : null;
}

export async function loadPersonalKeyVersion(
  user: WebUser, provider: PersonalKeyProvider, version: string,
): Promise<string | null> {
  const result = await userDatabase().query<{ sealed_key: Buffer }>(
    `SELECT sealed_key FROM ${userTable("user_provider_credentials")}
     WHERE issuer = $1 AND subject = $2 AND provider = $3 AND key_version = $4::uuid`,
    [user.issuer, user.subject, provider, version],
  );
  return result.rows[0] ? unsealPersonalKey(user, provider, result.rows[0].sealed_key) : null;
}

export async function savePersonalKey(user: WebUser, provider: PersonalKeyProvider, value: string): Promise<void> {
  const sealed = sealPersonalKey(user, provider, value);
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO ${userTable("user_provider_credentials")}
       (issuer, subject, provider, sealed_key, key_version, suffix)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (issuer, subject, provider) DO UPDATE SET
       sealed_key = EXCLUDED.sealed_key,
       key_version = EXCLUDED.key_version,
       suffix = EXCLUDED.suffix,
       updated_at = now()`,
      [user.issuer, user.subject, provider, sealed, randomUUID(), value.slice(-4)],
    );
    await revokeAdmissionsUsingProvider(client, user, provider);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function deletePersonalKey(user: WebUser, provider: PersonalKeyProvider): Promise<void> {
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `DELETE FROM ${userTable("user_provider_credentials")}
       WHERE issuer = $1 AND subject = $2 AND provider = $3`,
      [user.issuer, user.subject, provider],
    );
    await revokeAdmissionsUsingProvider(client, user, provider);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

async function revokeAdmissionsUsingProvider(
  client: { query: (sql: string, values?: unknown[]) => Promise<unknown> },
  user: WebUser,
  provider: PersonalKeyProvider,
): Promise<void> {
  await client.query(
    `UPDATE ${userTable("voice_admissions")} SET revoked_at = now()
     WHERE issuer = $1 AND subject = $2 AND $3 = ANY(personal_providers)
       AND ended_at IS NULL AND revoked_at IS NULL`,
    [user.issuer, user.subject, provider],
  );
}
