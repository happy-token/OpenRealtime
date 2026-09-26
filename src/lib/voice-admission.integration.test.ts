import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";

const enabled = process.env.RUN_POSTGRES_INTEGRATION === "1";
const suite = enabled ? describe : describe.skip;

suite("public voice admission with PostgreSQL", () => {
  const schema = `codex_voice_${randomBytes(5).toString("hex")}`;
  const dsn = process.env.TEST_POSTGRES_DSN || "postgresql://forever@localhost/postgres";
  const pool = new Pool({ connectionString: dsn });

  beforeAll(async () => {
    process.env.VOICEAGENT_POSTGRES_DSN = dsn;
    process.env.VOICEAGENT_POSTGRES_SCHEMA = schema;
    process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY = randomBytes(32).toString("base64url");
    process.env.VOICEAGENT_PUBLIC_ORIGIN = "https://voice.example.test";
    process.env.DOUBAO_API_KEY = "test-platform-doubao";
    process.env.DASHSCOPE_API_KEY = "test-platform-dashscope";
    process.env.DEEPSEEK_API_KEY = "test-platform-deepseek";
    await pool.query(`CREATE SCHEMA "${schema}"`);
    for (const migration of ["0020_web_identity_and_provider_credentials.sql", "0021_voice_admissions.sql"]) {
      const sql = readFileSync(path.join(process.cwd(), "server/persistence/postgres/migrations", migration), "utf8")
        .replaceAll("__VOICEAGENT_SCHEMA__", schema);
      await pool.query(sql);
    }
  });

  afterAll(async () => {
    await pool.query(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`);
    await pool.end();
  });

  it("separates speech pools, decrypts only the owner's key, and revokes a rotated binding", async () => {
    const { admitVoiceSession, cancelUnboundVoiceTicket, claimAnamVoiceTicket } = await import("./voice-admission");
    const { savePersonalKey } = await import("./user-provider-credentials");
    const user = { issuer: "https://identity.example.test", subject: "person-1" };
    await savePersonalKey(user, "doubao", "test-owner-doubao-key");
    const first = await admitVoiceSession(user, "dashscope");
    expect(first.sources.asr.source).toBe("personal");
    expect(first.sources.tts.source).toBe("platform");
    await expect(admitVoiceSession(null, "dashscope")).rejects.toMatchObject({ code: "speech_capacity_full" });

    const python = [
      "import asyncio, json",
      "from server.voice_session.public_admission import PublicVoiceTicketAuthenticator",
      `ticket = ${JSON.stringify(first.ticket)}`,
      "async def main():",
      "    identity = await PublicVoiceTicketAuthenticator().authenticate({'origin': 'https://voice.example.test'}, '/voice?admission=' + ticket)",
      "    print(json.dumps({'user': identity.user_id, 'asr_key': identity.admission.credentials['doubao']}))",
      "asyncio.run(main())",
    ].join("\n");
    const verified = JSON.parse(execFileSync("uv", ["run", "--extra", "postgres", "python", "-c", python], {
      cwd: process.cwd(), env: process.env, encoding: "utf8",
    }));
    expect(verified).toEqual({ user: `${user.issuer}#${user.subject}`, asr_key: "test-owner-doubao-key" });

    await savePersonalKey(user, "doubao", "test-rotated-doubao-key");
    const row = await pool.query<{ revoked_at: Date }>(
      `SELECT revoked_at FROM "${schema}".voice_admissions WHERE ticket_hash = $1`,
      [createHash("sha256").update(first.ticket).digest("hex")],
    );
    expect(row.rows[0]?.revoked_at).not.toBeNull();
    const second = await admitVoiceSession(user, "dashscope");
    expect(second.sources.asr.source).toBe("personal");
    expect(await cancelUnboundVoiceTicket(user, second.ticket)).toBe(true);

    await savePersonalKey(user, "anam", "test-owner-anam-key");
    const avatar = await admitVoiceSession(user, "dashscope", "anam");
    expect(avatar.sources.anam?.source).toBe("personal");
    const claimed = await claimAnamVoiceTicket(user, avatar.ticket);
    expect(claimed).toMatchObject({ source: "personal" });
    expect(await claimAnamVoiceTicket(user, avatar.ticket)).toBeNull();
    expect(await claimAnamVoiceTicket({ issuer: user.issuer, subject: "different" }, avatar.ticket)).toBeNull();
    await savePersonalKey(user, "anam", "test-new-anam-key");
    const revokedAvatar = await pool.query<{ revoked_at: Date }>(
      `SELECT revoked_at FROM "${schema}".voice_admissions WHERE ticket_hash = $1`,
      [createHash("sha256").update(avatar.ticket).digest("hex")],
    );
    expect(revokedAvatar.rows[0]?.revoked_at).not.toBeNull();
  });
});
