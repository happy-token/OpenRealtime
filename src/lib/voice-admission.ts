import { createHash, randomBytes, randomUUID } from "node:crypto";
import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";
import type { PersonalKeyProvider } from "./user-provider-credentials";

type Source = "personal" | "platform";
type SpeechProvider = "doubao" | "dashscope" | "bella";

export interface VoiceAdmission {
  ticket: string;
  sources: {
    asr: { provider: SpeechProvider; source: Source };
    tts: { provider: SpeechProvider; source: Source };
    llm: { provider: "deepseek" | "openai" | "custom" | "bella"; source: Source };
    anam?: { provider: "anam"; source: Source };
  };
  deadline: string | null;
}

export class VoiceAdmissionError extends Error {
  constructor(public readonly code: "credential_missing" | "speech_capacity_full" | "configuration_invalid", message: string, public readonly status: number) {
    super(message);
  }
}

function positiveSetting(name: string, defaultValue: number, maximum: number): number {
  const value = process.env[name];
  if (value === undefined) return defaultValue;
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1 || number > maximum) {
    throw new VoiceAdmissionError("configuration_invalid", `${name} 配置无效`, 503);
  }
  return number;
}

function currentProviders(ttsChoice: unknown): { asr: SpeechProvider; tts: SpeechProvider } {
  const asrBackend = process.env.VOICEAGENT_ASR_BACKEND || "doubao-direct";
  if (asrBackend !== "doubao-direct" && asrBackend !== "bella") {
    throw new VoiceAdmissionError("configuration_invalid", "当前语音识别服务配置无效", 503);
  }
  const asr: SpeechProvider = asrBackend === "bella" ? "bella" : "doubao";
  const defaultTts = process.env.VOICEAGENT_TTS_BACKEND === "bailian" ? "dashscope" : "doubao";
  const tts = ttsChoice === undefined ? defaultTts : ttsChoice;
  if (tts !== "doubao" && tts !== "dashscope") {
    throw new VoiceAdmissionError("configuration_invalid", "请选择有效的语音合成服务", 400);
  }
  return { asr, tts };
}

function platformKey(provider: SpeechProvider | "deepseek" | "openai" | "custom" | "anam"): string | undefined {
  const envName = {
    doubao: "DOUBAO_API_KEY",
    dashscope: "DASHSCOPE_API_KEY",
    bella: "API_KEY",
    deepseek: "DEEPSEEK_API_KEY",
    openai: "OPENAI_API_KEY",
    custom: "VOICEAGENT_LLM_API_KEY",
    anam: "ANAM_API_KEY",
  }[provider];
  return process.env[envName]?.trim() || undefined;
}

function ticketHash(ticket: string): string {
  return createHash("sha256").update(ticket).digest("hex");
}

/** Reserve both platform speech capabilities in one PostgreSQL transaction. */
export async function admitVoiceSession(user: WebUser | null, ttsChoice?: unknown, avatarProvider?: unknown): Promise<VoiceAdmission> {
  const providers = currentProviders(ttsChoice);
  if (avatarProvider !== undefined && avatarProvider !== "anam") {
    throw new VoiceAdmissionError("configuration_invalid", "数字人服务无效", 400);
  }
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtext('openrealtime-voice-speech-capacity'))");

    const versions = new Map<PersonalKeyProvider, string>();
    let personalLlmProvider: "deepseek" | "openai" | undefined;
    if (user) {
      const result = await client.query<{ provider: PersonalKeyProvider; key_version: string }>(
        `SELECT provider, key_version FROM ${userTable("user_provider_credentials")}
         WHERE issuer = $1 AND subject = $2 AND provider = ANY($3::text[])
         ORDER BY updated_at DESC, provider ASC`,
        [user.issuer, user.subject, [providers.asr, providers.tts, "deepseek", "openai", ...(avatarProvider ? ["anam"] : [])]],
      );
      for (const row of result.rows) versions.set(row.provider, row.key_version);
      personalLlmProvider = result.rows.find((row) => row.provider === "deepseek" || row.provider === "openai")?.provider as "deepseek" | "openai" | undefined;
    }
    const sourceFor = (provider: SpeechProvider | "deepseek" | "openai" | "custom" | "anam"): Source =>
      versions.has(provider as PersonalKeyProvider) ? "personal" : "platform";
    const asrSource = sourceFor(providers.asr);
    const ttsSource = sourceFor(providers.tts);
    const llmProvider = personalLlmProvider
      ?? (platformKey("custom") ? "custom" : platformKey("deepseek") ? "deepseek"
        : platformKey("openai") ? "openai" : "bella");
    const llmSource = llmProvider === "deepseek" || llmProvider === "openai" ? sourceFor(llmProvider) : "platform";
    const anamSource = avatarProvider === "anam" ? sourceFor("anam") : null;
    for (const [capability, provider, source] of [
      ["语音识别", providers.asr, asrSource],
      ["语音合成", providers.tts, ttsSource],
      ["对话模型", llmProvider, llmSource],
      ...(anamSource ? [["实时数字人", "anam", anamSource] as const] : []),
    ] as const) {
      if (source === "platform" && !platformKey(provider)) {
        throw new VoiceAdmissionError("credential_missing", `${capability}尚未配置可用的 API Key`, 503);
      }
    }

    if (asrSource === "platform" || ttsSource === "platform") {
      const capacity = await client.query<{ asr_count: string; tts_count: string }>(
        `SELECT COUNT(*) FILTER (WHERE asr_source = 'platform') AS asr_count,
                COUNT(*) FILTER (WHERE tts_source = 'platform') AS tts_count
         FROM ${userTable("voice_admissions")}
         WHERE ended_at IS NULL AND revoked_at IS NULL AND expires_at > now()
           AND (bound_session_id IS NOT NULL OR connect_by > now())`,
      );
      const counts = capacity.rows[0];
      if ((asrSource === "platform" && Number(counts.asr_count) >= positiveSetting("VOICEAGENT_PLATFORM_ASR_CONCURRENCY", 1, 1000))
        || (ttsSource === "platform" && Number(counts.tts_count) >= positiveSetting("VOICEAGENT_PLATFORM_TTS_CONCURRENCY", 1, 1000))) {
        throw new VoiceAdmissionError("speech_capacity_full", "平台语音服务当前满员，请稍后手动重试，或登录使用自己的 API Key。", 429);
      }
    }

    const limited = !user || asrSource === "platform" || ttsSource === "platform";
    const durationSeconds = limited ? positiveSetting("VOICEAGENT_PLATFORM_VOICE_SESSION_SECONDS", 180, 3600) : null;
    const ticket = randomBytes(32).toString("base64url");
    const personalProviders = [...new Set([providers.asr, providers.tts, llmProvider, ...(anamSource ? ["anam"] : [])]
      .filter((provider) => versions.has(provider as PersonalKeyProvider)))];
    const bindingVersions = Object.fromEntries(personalProviders.map((provider) =>
      [provider, versions.get(provider as PersonalKeyProvider)]));
    const deadline = durationSeconds ? new Date(Date.now() + durationSeconds * 1000).toISOString() : null;
    await client.query(
      `INSERT INTO ${userTable("voice_admissions")}
       (ticket_hash, issuer, subject, guest_id, asr_provider, asr_source,
        tts_provider, tts_source, llm_provider, llm_source, anam_source, personal_providers,
        credential_versions, connect_by, deadline_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
               now() + interval '60 seconds', $14, $15)`,
      [ticketHash(ticket), user?.issuer ?? null, user?.subject ?? null,
        user ? null : randomUUID(), providers.asr, asrSource, providers.tts, ttsSource,
        llmProvider, llmSource, anamSource, personalProviders, JSON.stringify(bindingVersions),
        deadline,
        deadline ? new Date(Date.parse(deadline) + 30_000).toISOString()
          : new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()],
    );
    await client.query("COMMIT");
    return {
      ticket,
      sources: {
        asr: { provider: providers.asr, source: asrSource },
        tts: { provider: providers.tts, source: ttsSource },
        llm: { provider: llmProvider, source: llmSource },
        ...(anamSource ? { anam: { provider: "anam" as const, source: anamSource } } : {}),
      },
      deadline,
    };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function ownsActiveVoiceTicket(user: WebUser | null, ticket: unknown): Promise<boolean> {
  if (typeof ticket !== "string" || !/^[A-Za-z0-9_-]{40,64}$/.test(ticket)) return false;
  const result = await userDatabase().query<{ issuer: string | null; subject: string | null }>(
    `SELECT issuer, subject FROM ${userTable("voice_admissions")}
     WHERE ticket_hash = $1 AND ended_at IS NULL AND revoked_at IS NULL
       AND connect_by > now() AND expires_at > now() AND bound_session_id IS NULL`,
    [ticketHash(ticket)],
  );
  const row = result.rows[0];
  return Boolean(row && (user
    ? row.issuer === user.issuer && row.subject === user.subject
    : row.issuer === null && row.subject === null));
}

export async function cancelUnboundVoiceTicket(user: WebUser | null, ticket: unknown): Promise<boolean> {
  if (!await ownsActiveVoiceTicket(user, ticket)) return false;
  const result = await userDatabase().query(
    `UPDATE ${userTable("voice_admissions")} SET ended_at = now()
     WHERE ticket_hash = $1 AND bound_session_id IS NULL AND ended_at IS NULL`,
    [ticketHash(ticket as string)],
  );
  return result.rowCount === 1;
}

export async function claimAnamVoiceTicket(user: WebUser | null, ticket: unknown): Promise<{ source: Source; version: string | null } | null> {
  if (!await ownsActiveVoiceTicket(user, ticket)) return null;
  const result = await userDatabase().query<{ anam_source: Source; credential_versions: Record<string, string> }>(
    `UPDATE ${userTable("voice_admissions")} SET anam_issued_at = now()
     WHERE ticket_hash = $1 AND anam_source IS NOT NULL AND anam_issued_at IS NULL
       AND bound_session_id IS NULL AND connect_by > now()
       AND ended_at IS NULL AND revoked_at IS NULL
     RETURNING anam_source, credential_versions`,
    [ticketHash(ticket as string)],
  );
  const row = result.rows[0];
  return row ? { source: row.anam_source, version: row.credential_versions.anam ?? null } : null;
}
