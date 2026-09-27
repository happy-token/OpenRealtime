import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";
import { normalizeProviderBaseUrl, PROVIDER_CATALOG } from "./provider-catalog";
import { loadPlatformProviderKey } from "./platform-provider-credentials";

export type ProviderCapability = "asr" | "tts" | "llm";
export type ProviderScope = "personal" | "platform";
export type BuiltinProvider = "doubao" | "dashscope" | "deepseek" | "openai";
export type ProviderConnectionStatus = "untested" | "passed" | "failed";

export interface ProviderInstance {
  id: string;
  scope: ProviderScope;
  capability: ProviderCapability;
  provider: BuiltinProvider;
  displayName: string;
  model: string;
  baseUrl: string;
  enabled: boolean;
  keySuffix: string;
  connectionStatus: ProviderConnectionStatus;
  testedAt: string | null;
  testMessage: string | null;
  revision: string;
  updatedAt: string;
}

export interface ProviderInstanceInput {
  capability: ProviderCapability;
  provider: BuiltinProvider;
  displayName: string;
  model: string;
  baseUrl?: string;
  apiKey?: string;
  enabled?: boolean;
  expectedRevision?: string;
}

export class ProviderInstanceQuotaError extends Error {}
export class ProviderInstanceNotReadyError extends Error {}

const PROVIDERS: Record<ProviderCapability, readonly BuiltinProvider[]> = {
  asr: ["doubao", "dashscope"],
  tts: ["doubao", "dashscope"],
  llm: ["deepseek", "openai"],
};

export function parseProviderCapability(value: unknown): ProviderCapability | null {
  return value === "asr" || value === "tts" || value === "llm" ? value : null;
}

export function parseBuiltinProvider(value: unknown, capability: ProviderCapability): BuiltinProvider | null {
  return typeof value === "string" && PROVIDERS[capability].includes(value as BuiltinProvider)
    ? value as BuiltinProvider : null;
}

export function validateProviderInstanceInput(value: unknown, existing = false): ProviderInstanceInput | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  const capability = parseProviderCapability(body.capability);
  const provider = capability && parseBuiltinProvider(body.provider, capability);
  const displayName = body.displayName;
  const model = body.model === undefined ? "" : body.model;
  const baseUrl = body.baseUrl === undefined && capability && provider
    ? PROVIDER_CATALOG[capability].find((item) => item.id === provider)?.baseUrl : body.baseUrl;
  const apiKey = body.apiKey;
  const expectedRevision = body.expectedRevision;
  if (!capability || !provider || typeof displayName !== "string" || !displayName.trim()
    || displayName.length > 80 || /[\x00-\x1f\x7f]/.test(displayName)
    || typeof model !== "string" || model.length > 100 || /[\x00-\x1f\x7f]/.test(model)
    || (capability !== "llm" && model !== "")
    || typeof baseUrl !== "string" || !normalizeProviderBaseUrl(capability, provider, baseUrl)
    || (!existing && typeof apiKey !== "string")
    || (apiKey !== undefined && (typeof apiKey !== "string" || apiKey.length < 8
      || apiKey.length > 512 || apiKey !== apiKey.trim() || /[\x00-\x1f\x7f]/.test(apiKey)))
    || (body.enabled !== undefined && typeof body.enabled !== "boolean")) return null;
  if (existing && (typeof expectedRevision !== "string" || !/^[0-9a-f-]{36}$/i.test(expectedRevision))) return null;
  return { capability, provider, displayName: displayName.trim(), model: model.trim(),
    baseUrl: normalizeProviderBaseUrl(capability, provider, baseUrl)!,
    ...(apiKey === undefined ? {} : { apiKey }),
    ...(expectedRevision === undefined ? {} : { expectedRevision: expectedRevision as string }),
    ...(body.enabled === undefined ? {} : { enabled: body.enabled }) };
}

function owner(scope: ProviderScope, user: WebUser): [string, string] {
  return scope === "platform" ? ["", ""] : [user.issuer, user.subject];
}

function encryptionKey(): Buffer {
  const encoded = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded) throw new Error("供应商凭据加密密钥尚未配置");
  const bytes = Buffer.from(encoded, "base64url");
  if (bytes.length !== 32 || bytes.toString("base64url") !== encoded.replace(/=+$/, "")) {
    throw new Error("供应商凭据加密密钥格式无效");
  }
  return bytes;
}

function aad(id: string, scope: ProviderScope, issuer: string, subject: string): Buffer {
  return Buffer.from(JSON.stringify(["provider_instance", scope, issuer, subject, id]));
}

function sealKey(id: string, scope: ProviderScope, issuer: string, subject: string, key: string): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(aad(id, scope, issuer, subject));
  return Buffer.concat([iv, cipher.update(key, "utf8"), cipher.final(), cipher.getAuthTag()]);
}

function openKey(id: string, scope: ProviderScope, issuer: string, subject: string, sealed: Buffer): string {
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), sealed.subarray(0, 12));
  decipher.setAAD(aad(id, scope, issuer, subject));
  decipher.setAuthTag(sealed.subarray(-16));
  return Buffer.concat([decipher.update(sealed.subarray(12, -16)), decipher.final()]).toString("utf8");
}

type InstanceRow = {
  id: string; scope: ProviderScope; capability: ProviderCapability; provider: BuiltinProvider;
  display_name: string; model: string; base_url: string; enabled: boolean; key_suffix: string;
  connection_status: ProviderConnectionStatus; tested_at: Date | null;
  test_message: string | null; key_version: string; updated_at: Date;
};

function publicInstance(row: InstanceRow): ProviderInstance {
  return {
    id: row.id, scope: row.scope, capability: row.capability, provider: row.provider,
    displayName: row.display_name, model: row.model, baseUrl: row.base_url, enabled: row.enabled,
    keySuffix: row.key_suffix, connectionStatus: row.connection_status,
    testedAt: row.tested_at?.toISOString() ?? null, testMessage: row.test_message,
    revision: row.key_version,
    updatedAt: row.updated_at.toISOString(),
  };
}

export async function listProviderInstances(user: WebUser, admin: boolean): Promise<{
  instances: ProviderInstance[]; selections: Partial<Record<ProviderCapability, string>>;
  platformSelections: Partial<Record<ProviderCapability, string>>;
}> {
  const [instances, selections, platformSelections] = await Promise.all([
    userDatabase().query<InstanceRow>(
      `SELECT id, scope, capability, provider, display_name, model, base_url, enabled, key_suffix, key_version,
              connection_status, tested_at, test_message, updated_at
       FROM ${userTable("provider_instances")}
       WHERE (scope = 'personal' AND issuer = $1 AND subject = $2)
          OR (scope = 'platform' AND ($3::boolean OR enabled))
       ORDER BY capability, scope DESC, created_at DESC LIMIT 500`,
      [user.issuer, user.subject, admin],
    ),
    userDatabase().query<{ capability: ProviderCapability; instance_id: string | null; env_provider: string | null }>(
      `SELECT capability, instance_id, env_provider FROM ${userTable("provider_selections")}
       WHERE scope = 'personal' AND issuer = $1 AND subject = $2`,
      [user.issuer, user.subject],
    ),
    userDatabase().query<{ capability: ProviderCapability; instance_id: string | null; env_provider: string | null }>(
      `SELECT capability, instance_id, env_provider FROM ${userTable("provider_selections")}
       WHERE scope = 'platform' AND issuer = '' AND subject = ''`,
    ),
  ]);
  return { instances: instances.rows.map(publicInstance),
    selections: Object.fromEntries(selections.rows.map((row) => [row.capability, row.instance_id ?? `env:${row.env_provider}`])),
    platformSelections: Object.fromEntries(platformSelections.rows.map((row) => [row.capability, row.instance_id ?? `env:${row.env_provider}`])) };
}

export async function createProviderInstance(user: WebUser, scope: ProviderScope, input: ProviderInstanceInput): Promise<ProviderInstance> {
  if (!input.apiKey) throw new Error("API Key is required");
  const [issuer, subject] = owner(scope, user);
  const id = randomUUID();
  const sealed = sealKey(id, scope, issuer, subject, input.apiKey);
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [`provider-instance:${scope}:${issuer}:${subject}:${input.capability}`]);
    const count = await client.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM ${userTable("provider_instances")}
       WHERE scope = $1 AND issuer = $2 AND subject = $3 AND capability = $4`,
      [scope, issuer, subject, input.capability],
    );
    if (Number(count.rows[0]?.count ?? 0) >= (scope === "platform" ? 100 : 50)) {
      throw new ProviderInstanceQuotaError("该能力的配置数量已达上限");
    }
    const result = await client.query<InstanceRow>(
    `INSERT INTO ${userTable("provider_instances")}
     (id, scope, issuer, subject, capability, provider, display_name, model, base_url, sealed_key,
      key_version, key_suffix, enabled)
     VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::uuid, $12, $13)
     RETURNING id, scope, capability, provider, display_name, model, base_url, enabled, key_suffix, key_version,
               connection_status, tested_at, test_message, updated_at`,
    [id, scope, issuer, subject, input.capability, input.provider, input.displayName,
      input.model, input.baseUrl, sealed, randomUUID(), input.apiKey.slice(-4), input.enabled ?? true],
    );
    await client.query("COMMIT");
    return publicInstance(result.rows[0]);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}

export async function updateProviderInstance(
  user: WebUser, scope: ProviderScope, id: string, input: ProviderInstanceInput,
): Promise<ProviderInstance | null> {
  const [issuer, subject] = owner(scope, user);
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    const existing = await client.query<{ capability: ProviderCapability; provider: BuiltinProvider; key_version: string }>(
      `SELECT capability, provider, key_version FROM ${userTable("provider_instances")}
       WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4 FOR UPDATE`,
      [id, scope, issuer, subject],
    );
    if (!existing.rows[0]) { await client.query("ROLLBACK"); return null; }
    if (existing.rows[0].capability !== input.capability || existing.rows[0].provider !== input.provider) {
      throw new Error("供应商能力和类型不可修改，请新建实例");
    }
    if (existing.rows[0].key_version !== input.expectedRevision) throw new Error("配置已被其他操作修改，请刷新后重试");
    const sealed = input.apiKey ? sealKey(id, scope, issuer, subject, input.apiKey) : null;
    const result = await client.query<InstanceRow>(
      `UPDATE ${userTable("provider_instances")}
       SET display_name = $5, model = $6, enabled = $7, base_url = $11,
           sealed_key = COALESCE($8::bytea, sealed_key),
           key_version = $9::uuid,
           key_suffix = COALESCE($10, key_suffix), connection_status = 'untested',
           tested_at = NULL, test_message = NULL, updated_at = now()
       WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4
       RETURNING id, scope, capability, provider, display_name, model, base_url, enabled, key_suffix, key_version,
                 connection_status, tested_at, test_message, updated_at`,
      [id, scope, issuer, subject, input.displayName, input.model, input.enabled ?? true,
        sealed, randomUUID(), input.apiKey?.slice(-4) ?? null, input.baseUrl],
    );
    await revokeInstanceAdmissions(client, id);
    await client.query("COMMIT");
    return publicInstance(result.rows[0]);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}

export async function deleteProviderInstance(user: WebUser, scope: ProviderScope, id: string): Promise<boolean> {
  const [issuer, subject] = owner(scope, user);
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    const owned = await client.query(
      `SELECT id FROM ${userTable("provider_instances")}
       WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4 FOR UPDATE`,
      [id, scope, issuer, subject],
    );
    if (!owned.rowCount) { await client.query("ROLLBACK"); return false; }
    const selected = await client.query(
      `SELECT 1 FROM ${userTable("provider_selections")} WHERE instance_id = $1::uuid LIMIT 1`, [id],
    );
    if (selected.rowCount) throw new Error("请先切换正在使用的实例，再删除此配置");
    const roleSelected = await client.query(
      `SELECT 1 FROM ${userTable("role_tts_selections")} WHERE target = $1 LIMIT 1`, [id],
    );
    if (roleSelected.rowCount) throw new Error("请先切换角色正在使用的语音配置，再删除此配置");
    const result = await client.query(
      `DELETE FROM ${userTable("provider_instances")}
       WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4`,
      [id, scope, issuer, subject],
    );
    if (result.rowCount) await revokeInstanceAdmissions(client, id);
    await client.query("COMMIT");
    return Boolean(result.rowCount);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}

export async function selectProviderInstance(user: WebUser, id: string, selectionScope: ProviderScope = "personal"): Promise<ProviderInstance | null> {
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    const result = await client.query<InstanceRow>(
      `SELECT id, scope, capability, provider, display_name, model, base_url, enabled, key_suffix, key_version,
              connection_status, tested_at, test_message, updated_at
       FROM ${userTable("provider_instances")}
       WHERE id = $1::uuid AND enabled
         AND ($4 = 'personal' AND ((scope = 'personal' AND issuer = $2 AND subject = $3) OR scope = 'platform')
           OR $4 = 'platform' AND scope = 'platform')
       FOR SHARE`,
      [id, user.issuer, user.subject, selectionScope],
    );
    const row = result.rows[0];
    if (!row) { await client.query("ROLLBACK"); return null; }
    if (row.connection_status !== "passed") {
      throw new ProviderInstanceNotReadyError("请先通过实时能力测试，再设为当前使用");
    }
    await client.query(
      `INSERT INTO ${userTable("provider_selections")}
       (scope, issuer, subject, capability, instance_id, env_provider)
       VALUES ($5, $1, $2, $3, $4::uuid, NULL)
       ON CONFLICT (scope, issuer, subject, capability)
       DO UPDATE SET instance_id = EXCLUDED.instance_id, env_provider = NULL, updated_at = now()`,
      [selectionScope === "platform" ? "" : user.issuer,
        selectionScope === "platform" ? "" : user.subject,
        row.capability, id, selectionScope],
    );
    await client.query("COMMIT");
    return publicInstance(row);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}

export async function selectPlatformEnvironmentProvider(
  user: WebUser, capability: ProviderCapability, provider: BuiltinProvider,
  scope: ProviderScope = "personal",
): Promise<boolean> {
  if (!parseBuiltinProvider(provider, capability) || !loadPlatformProviderKey(capability, provider)) return false;
  const [issuer, subject] = owner(scope, user);
  await userDatabase().query(
    `INSERT INTO ${userTable("provider_selections")}
     (scope, issuer, subject, capability, instance_id, env_provider)
     VALUES ($1, $2, $3, $4, NULL, $5)
     ON CONFLICT (scope, issuer, subject, capability)
     DO UPDATE SET instance_id = NULL, env_provider = EXCLUDED.env_provider, updated_at = now()`,
    [scope, issuer, subject, capability, provider],
  );
  return true;
}

export async function clearProviderSelection(user: WebUser, capability: ProviderCapability,
  scope: ProviderScope = "personal"): Promise<boolean> {
  const [issuer, subject] = owner(scope, user);
  const result = await userDatabase().query(
    `DELETE FROM ${userTable("provider_selections")}
     WHERE scope = $1 AND issuer = $2 AND subject = $3 AND capability = $4`,
    [scope, issuer, subject, capability],
  );
  return Boolean(result.rowCount);
}

export async function loadProviderInstanceKey(user: WebUser, id: string, admin: boolean): Promise<{
  instance: ProviderInstance; key: string; keyVersion: string;
} | null> {
  const result = await userDatabase().query<InstanceRow & { issuer: string; subject: string; sealed_key: Buffer; key_version: string }>(
    `SELECT id, scope, issuer, subject, capability, provider, display_name, model, base_url, enabled,
            sealed_key, key_version, key_suffix, connection_status, tested_at, test_message, updated_at
     FROM ${userTable("provider_instances")}
     WHERE id = $1::uuid AND ((scope = 'personal' AND issuer = $2 AND subject = $3)
       OR (scope = 'platform' AND $4::boolean))`,
    [id, user.issuer, user.subject, admin],
  );
  const row = result.rows[0];
  return row ? { instance: publicInstance(row), key: openKey(id, row.scope, row.issuer, row.subject, row.sealed_key),
    keyVersion: row.key_version } : null;
}

export async function recordProviderConnectionTest(
  user: WebUser, scope: ProviderScope, id: string, version: string, passed: boolean, message: string,
): Promise<boolean> {
  const [issuer, subject] = owner(scope, user);
  const result = await userDatabase().query(
    `UPDATE ${userTable("provider_instances")}
     SET connection_status = $5, tested_at = now(), test_message = $6
     WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4
       AND key_version = $7::uuid`,
    [id, scope, issuer, subject, passed ? "passed" : "failed", message.slice(0, 200), version],
  );
  return result.rowCount === 1;
}

export async function claimProviderConnectionTest(
  user: WebUser, scope: ProviderScope, id: string, version: string,
): Promise<boolean> {
  const [issuer, subject] = owner(scope, user);
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtext($1))",
      [`provider-test:${scope}:${issuer}:${subject}`]);
    const recent = await client.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM ${userTable("provider_instances")}
       WHERE scope = $1 AND issuer = $2 AND subject = $3
         AND test_last_started_at >= now() - interval '60 seconds'`,
      [scope, issuer, subject],
    );
    if (Number(recent.rows[0]?.count ?? 0) >= 3) {
      await client.query("ROLLBACK");
      return false;
    }
    const result = await client.query(
      `UPDATE ${userTable("provider_instances")}
       SET test_last_started_at = now()
       WHERE id = $1::uuid AND scope = $2 AND issuer = $3 AND subject = $4
         AND key_version = $5::uuid
         AND (test_last_started_at IS NULL OR test_last_started_at < now() - interval '60 seconds')`,
      [id, scope, issuer, subject, version],
    );
    await client.query("COMMIT");
    return result.rowCount === 1;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}

async function revokeInstanceAdmissions(
  client: { query: (sql: string, values?: unknown[]) => Promise<unknown> }, id: string,
): Promise<void> {
  await client.query(
    `UPDATE ${userTable("voice_admissions")} SET revoked_at = now()
     WHERE ended_at IS NULL AND revoked_at IS NULL
       AND (provider_instances->'asr'->>'id' = $1
         OR provider_instances->'tts'->>'id' = $1
         OR provider_instances->'llm'->>'id' = $1)`,
    [id],
  );
}
