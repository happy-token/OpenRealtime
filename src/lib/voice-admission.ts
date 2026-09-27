import { createHash, randomBytes, randomUUID } from "node:crypto";
import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";
import type { PersonalKeyProvider } from "./user-provider-credentials";
import type { ProviderCapability, ProviderScope } from "./provider-instances";
import { isRoleRecordId } from "./role-records";

type Source = "personal" | "platform";
type SpeechProvider = "doubao" | "dashscope" | "bella";
type SelectedInstance = { id: string; scope: ProviderScope; capability: ProviderCapability;
  provider: string; model: string; base_url: string; display_name: string; key_version: string; enabled: boolean;
  connection_status: "untested" | "passed" | "failed"; selection_scope?: ProviderScope };

export interface VoiceAdmission {
  ticket: string;
  sources: {
    asr: { provider: SpeechProvider; source: Source; instanceName?: string };
    tts: { provider: SpeechProvider; source: Source; instanceName?: string };
    llm: { provider: "deepseek" | "openai" | "custom" | "bella"; source: Source; instanceName?: string };
    anam?: { provider: "anam"; source: Source };
  };
  deadline: string | null;
  instances?: Partial<Record<ProviderCapability, string>>;
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
  if (asrBackend !== "doubao-direct") {
    throw new VoiceAdmissionError("configuration_invalid", "当前语音识别服务配置无效", 503);
  }
  const asr: SpeechProvider = "doubao";
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
export async function admitVoiceSession(user: WebUser | null, ttsChoice?: unknown, avatarProvider?: unknown, roleId?: unknown): Promise<VoiceAdmission> {
  const providers = currentProviders(ttsChoice);
  if (roleId !== undefined && roleId !== null && !isRoleRecordId(roleId)) {
    throw new VoiceAdmissionError("configuration_invalid", "角色无效", 400);
  }
  if (avatarProvider !== undefined && avatarProvider !== "anam") {
    throw new VoiceAdmissionError("configuration_invalid", "数字人服务无效", 400);
  }
  const client = await userDatabase().connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtext('openrealtime-voice-speech-capacity'))");

    const versions = new Map<PersonalKeyProvider, string>();
    let personalLlmProvider: "deepseek" | "openai" | undefined;
    const selected = new Map<ProviderCapability, SelectedInstance>();
    const selectedRows = await client.query<SelectedInstance>(
        `SELECT i.id, i.scope, i.capability, i.provider, i.model, i.base_url, i.display_name, i.key_version,
                s.scope AS selection_scope,
                i.enabled, i.connection_status
         FROM ${userTable("provider_selections")} s
         JOIN ${userTable("provider_instances")} i ON i.id = s.instance_id
         WHERE (($3::boolean AND s.scope = 'personal' AND s.issuer = $1 AND s.subject = $2)
           OR (s.scope = 'platform' AND s.issuer = '' AND s.subject = ''))
           AND (($3::boolean AND i.scope = 'personal' AND i.issuer = $1 AND i.subject = $2)
             OR i.scope = 'platform')
         ORDER BY CASE WHEN s.scope = 'personal' THEN 0 ELSE 1 END
         FOR SHARE OF i`,
        [user?.issuer ?? "", user?.subject ?? "", Boolean(user)],
      );
    const environmentRows = await client.query<{ capability: ProviderCapability; provider: string; scope: ProviderScope }>(
      `SELECT e.capability, e.env_provider AS provider, e.scope
       FROM ${userTable("provider_selections")} e
       WHERE e.env_provider IS NOT NULL
         AND (($3::boolean AND e.scope = 'personal' AND e.issuer = $1 AND e.subject = $2)
           OR (e.scope = 'platform' AND e.issuer = '' AND e.subject = ''))`,
      [user?.issuer ?? "", user?.subject ?? "", Boolean(user)],
    );
    const choices = new Map<ProviderCapability, { priority: number; instance?: SelectedInstance; environment?: string }>();
    for (const row of selectedRows.rows) {
      const priority = (row.selection_scope ?? row.scope) === "personal" ? 0 : 1;
      if (!choices.has(row.capability) || priority < choices.get(row.capability)!.priority) {
        choices.set(row.capability, { priority, instance: row });
      }
    }
    for (const row of environmentRows.rows) {
      const priority = row.scope === "personal" ? 0 : 1;
      if (!choices.has(row.capability) || priority < choices.get(row.capability)!.priority) {
        choices.set(row.capability, { priority, environment: row.provider });
      }
    }
    if (user && roleId) {
      const roleSelection = await client.query<{ target: string }>(
        `SELECT target FROM ${userTable("role_tts_selections")}
         WHERE issuer = $1 AND subject = $2 AND role_id = $3`,
        [user.issuer, user.subject, roleId],
      );
      const target = roleSelection.rows[0]?.target;
      if (target?.startsWith("env:")) {
        const provider = target.slice(4);
        if (provider !== providers.tts || !platformKey(provider as SpeechProvider)) {
          throw new VoiceAdmissionError("configuration_invalid", "角色选择的 TTS 配置与音色不一致或已不可用", 409);
        }
        choices.set("tts", { priority: -1, environment: provider });
      } else if (target) {
        const roleInstance = await client.query<SelectedInstance>(
          `SELECT id, scope, capability, provider, model, base_url, display_name, key_version,
                  enabled, connection_status
           FROM ${userTable("provider_instances")} i
           WHERE id = $1::uuid AND capability = 'tts'
             AND ((scope = 'personal' AND issuer = $2 AND subject = $3)
               OR (scope = 'platform' AND issuer = '' AND subject = ''))
           FOR SHARE OF i`,
          [target, user.issuer, user.subject],
        );
        const row = roleInstance.rows[0];
        if (!row || row.provider !== providers.tts || !row.enabled || row.connection_status !== "passed") {
          throw new VoiceAdmissionError("configuration_invalid", "角色选择的 TTS 配置与音色不一致或已不可用", 409);
        }
        choices.set("tts", { priority: -1, instance: row });
      }
    }
    const environmentSelected = new Map<ProviderCapability, string>();
    for (const [capability, choice] of choices) {
      if (choice.environment) {
        if (!platformKey(choice.environment as SpeechProvider)) {
          throw new VoiceAdmissionError("credential_missing", "已选平台供应商缺少 API Key", 503);
        }
        environmentSelected.set(capability, choice.environment);
        continue;
      }
      const row = choice.instance!;
      if (!row.enabled) throw new VoiceAdmissionError("configuration_invalid", "已选供应商实例已停用，请重新选择", 409);
      if (row.connection_status !== "passed") {
        throw new VoiceAdmissionError("configuration_invalid", "已选供应商实例未通过实时能力测试，请重新测试", 409);
      }
      selected.set(capability, row);
    }
    const selectedAsr = selected.get("asr");
    const selectedLlm = selected.get("llm");
    if (selectedAsr || environmentSelected.has("asr")) {
      providers.asr = (selectedAsr?.provider ?? environmentSelected.get("asr")) as SpeechProvider;
    }
    if (selected.has("tts") || environmentSelected.has("tts")) {
      const chosenTts = selected.get("tts")?.provider ?? environmentSelected.get("tts")!;
      if (ttsChoice !== undefined && ttsChoice !== chosenTts) {
        // The global TTS selection is only a default. A role's voice always fixes
        // its provider; bind a tested instance of that provider when available.
        selected.delete("tts");
        environmentSelected.delete("tts");
        const compatible = await client.query<SelectedInstance>(
          `SELECT id, scope, capability, provider, model, base_url, display_name, key_version,
                  enabled, connection_status
           FROM ${userTable("provider_instances")}
           WHERE capability = 'tts' AND provider = $3 AND enabled = true
             AND connection_status = 'passed'
             AND (($4::boolean AND scope = 'personal' AND issuer = $1 AND subject = $2)
               OR (scope = 'platform' AND issuer = '' AND subject = ''))
           ORDER BY CASE WHEN scope = 'personal' THEN 0 ELSE 1 END, updated_at DESC, id
           LIMIT 1 FOR SHARE`,
          [user?.issuer ?? "", user?.subject ?? "", ttsChoice, Boolean(user)],
        );
        if (compatible.rows[0]) selected.set("tts", compatible.rows[0]);
        providers.tts = ttsChoice as SpeechProvider;
      } else {
        providers.tts = chosenTts as SpeechProvider;
      }
    }
    const selectedTts = selected.get("tts");
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
    const asrSource = selected.get("asr")?.scope ?? (environmentSelected.has("asr") ? "platform" : sourceFor(providers.asr));
    const ttsSource = selected.get("tts")?.scope ?? (environmentSelected.has("tts") ? "platform" : sourceFor(providers.tts));
    const llmProvider = (selectedLlm?.provider as "deepseek" | "openai" | undefined)
      ?? (environmentSelected.get("llm") as "deepseek" | "openai" | undefined) ?? personalLlmProvider
      ?? (platformKey("custom") ? "custom" : platformKey("deepseek") ? "deepseek"
        : platformKey("openai") ? "openai" : "bella");
    const llmSource = selectedLlm?.scope ?? (environmentSelected.has("llm") ? "platform"
      : llmProvider === "deepseek" || llmProvider === "openai" ? sourceFor(llmProvider) : "platform");
    const anamSource = avatarProvider === "anam" ? sourceFor("anam") : null;
    for (const [capability, provider, source] of [
      ["语音识别", providers.asr, asrSource],
      ["语音合成", providers.tts, ttsSource],
      ["对话模型", llmProvider, llmSource],
      ...(anamSource ? [["实时数字人", "anam", anamSource] as const] : []),
    ] as const) {
      const instanceCapability = capability === "语音识别" ? "asr" : capability === "语音合成" ? "tts"
        : capability === "对话模型" ? "llm" : null;
      if (source === "platform" && !(instanceCapability && selected.has(instanceCapability)) && !platformKey(provider)) {
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
    const personalProviders = [...new Set([
      ...(!selected.has("asr") && !environmentSelected.has("asr") ? [providers.asr] : []),
      ...(!selected.has("tts") && !environmentSelected.has("tts") ? [providers.tts] : []),
      ...(!selected.has("llm") && !environmentSelected.has("llm") ? [llmProvider] : []),
      ...(anamSource ? ["anam"] : []),
    ].filter((provider) => versions.has(provider as PersonalKeyProvider)))];
    const bindingVersions = Object.fromEntries(personalProviders.map((provider) =>
      [provider, versions.get(provider as PersonalKeyProvider)]));
    const instanceBindings = Object.fromEntries([...selected].map(([capability, row]) =>
      [capability, { id: row.id, scope: row.scope, version: row.key_version,
        provider: row.provider, model: row.model }]));
    const deadline = durationSeconds ? new Date(Date.now() + durationSeconds * 1000).toISOString() : null;
    await client.query(
      `INSERT INTO ${userTable("voice_admissions")}
       (ticket_hash, issuer, subject, guest_id, asr_provider, asr_source,
        tts_provider, tts_source, llm_provider, llm_source, anam_source, personal_providers,
        credential_versions, provider_instances, connect_by, deadline_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
               now() + interval '60 seconds', $15, $16)`,
      [ticketHash(ticket), user?.issuer ?? null, user?.subject ?? null,
        user ? null : randomUUID(), providers.asr, asrSource, providers.tts, ttsSource,
        llmProvider, llmSource, anamSource, personalProviders, JSON.stringify(bindingVersions),
        JSON.stringify(instanceBindings),
        deadline,
        deadline ? new Date(Date.parse(deadline) + 30_000).toISOString()
          : new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()],
    );
    await client.query("COMMIT");
    return {
      ticket,
      sources: {
        asr: { provider: providers.asr, source: asrSource,
          ...(selectedAsr ? { instanceName: selectedAsr.display_name } : {}) },
        tts: { provider: providers.tts, source: ttsSource,
          ...(selectedTts ? { instanceName: selectedTts.display_name } : {}) },
        llm: { provider: llmProvider, source: llmSource,
          ...(selectedLlm ? { instanceName: selectedLlm.display_name } : {}) },
        ...(anamSource ? { anam: { provider: "anam" as const, source: anamSource } } : {}),
      },
      deadline,
      instances: Object.fromEntries([...selected].map(([capability, row]) => [capability, row.id])),
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
