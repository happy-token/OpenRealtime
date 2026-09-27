import { userDatabase, userTable } from "./user-db";
import { loadPlatformProviderKey } from "./platform-provider-credentials";
import { isRoleRecordId } from "./role-records";
import type { WebUser } from "./user-session";

export type RoleTtsTarget = `env:${"doubao" | "dashscope"}` | string;
export type TtsProviderId = "doubao" | "dashscope";

export function isRoleTtsTarget(value: unknown): value is RoleTtsTarget {
  return typeof value === "string" && (value === "env:doubao" || value === "env:dashscope"
    || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value));
}

export async function getRoleTtsTarget(user: WebUser, roleId: string): Promise<string | null> {
  if (!isRoleRecordId(roleId)) return null;
  const result = await userDatabase().query<{ target: string }>(
    `SELECT target FROM ${userTable("role_tts_selections")}
     WHERE issuer = $1 AND subject = $2 AND role_id = $3`,
    [user.issuer, user.subject, roleId],
  );
  return result.rows[0]?.target ?? null;
}

export async function resolveRoleTtsTarget(user: WebUser, target: string): Promise<{
  provider: TtsProviderId; scope: "personal" | "platform";
} | null> {
  if (!isRoleTtsTarget(target)) return null;
  if (target.startsWith("env:")) {
    const provider = target.slice(4) as TtsProviderId;
    return loadPlatformProviderKey("tts", provider) ? { provider, scope: "platform" } : null;
  }
  const result = await userDatabase().query<{ provider: TtsProviderId; scope: "personal" | "platform" }>(
    `SELECT provider, scope FROM ${userTable("provider_instances")}
     WHERE id = $1::uuid AND capability = 'tts' AND enabled = true AND connection_status = 'passed'
       AND ((scope = 'personal' AND issuer = $2 AND subject = $3)
         OR (scope = 'platform' AND issuer = '' AND subject = ''))`,
    [target, user.issuer, user.subject],
  );
  const row = result.rows[0];
  return row && (row.provider === "doubao" || row.provider === "dashscope") ? row : null;
}

export async function saveRoleTtsTarget(user: WebUser, roleId: string, target: string): Promise<void> {
  if (!isRoleRecordId(roleId) || !isRoleTtsTarget(target)) throw new Error("角色语音配置无效");
  await userDatabase().query(
    `INSERT INTO ${userTable("role_tts_selections")} (issuer, subject, role_id, target)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (issuer, subject, role_id) DO UPDATE SET target = EXCLUDED.target, updated_at = now()`,
    [user.issuer, user.subject, roleId, target],
  );
}

export async function clearRoleTtsTarget(user: WebUser, roleId: string): Promise<void> {
  if (!isRoleRecordId(roleId)) throw new Error("角色无效");
  await userDatabase().query(
    `DELETE FROM ${userTable("role_tts_selections")}
     WHERE issuer = $1 AND subject = $2 AND role_id = $3`,
    [user.issuer, user.subject, roleId],
  );
}
