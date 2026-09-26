import { Pool } from "pg";

const SCHEMA_NAME = /^[a-z_][a-z0-9_]*$/;

let pool: Pool | undefined;

export function userDatabase(): Pool {
  const connectionString = process.env.VOICEAGENT_POSTGRES_DSN;
  if (!connectionString) throw new Error("用户凭据存储尚未配置 PostgreSQL");
  if (!pool) pool = new Pool({ connectionString, max: 5 });
  return pool;
}

export function userTable(name: "web_user_sessions" | "user_provider_credentials" | "voice_admissions" | "user_lipsync_services"): string {
  const schema = process.env.VOICEAGENT_POSTGRES_SCHEMA || "voiceagent";
  if (!SCHEMA_NAME.test(schema)) throw new Error("PostgreSQL schema 名称无效");
  return `"${schema}"."${name}"`;
}
