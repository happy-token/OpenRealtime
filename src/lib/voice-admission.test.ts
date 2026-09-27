import { afterEach, describe, expect, it, vi } from "vitest";

const database = vi.hoisted(() => ({
  client: { query: vi.fn(), release: vi.fn() },
  connect: vi.fn(),
}));
const roleLookup = vi.hoisted(() => ({ shared: vi.fn(), personal: vi.fn() }));
vi.mock("./role-catalog-repository", () => ({ findRole: roleLookup.shared }));
vi.mock("./personal-role-library", () => ({ findPersonalRole: roleLookup.personal }));
vi.mock("./user-db", () => ({
  userDatabase: () => ({ connect: database.connect }),
  userTable: (name: string) => `voiceagent.${name}`,
}));

import { admitVoiceSession, VoiceAdmissionError } from "./voice-admission";

function setup(versions: { provider: string; key_version: string }[], asrCount: number, ttsCount: number,
  selected: { id: string; scope: "personal" | "platform"; capability: "asr" | "tts" | "llm";
    provider: string; model: string; display_name: string; key_version: string; enabled: boolean;
    connection_status?: "passed" | "failed" | "untested" }[] = [],
  environmentSelections: { capability: "asr" | "tts" | "llm"; provider: string; scope: "personal" | "platform" }[] = [],
  compatibleTts: typeof selected = [], roleTarget: string | null = null, roleInstance: typeof selected = []) {
  database.connect.mockResolvedValue(database.client);
  database.client.query.mockImplementation(async (sql: string) => {
    if (sql.includes("SELECT provider, key_version")) return { rows: versions };
    if (sql.includes("FROM voiceagent.provider_selections s")) return { rows: selected.map((row) => ({
      connection_status: "passed", ...row,
    })) };
    if (sql.includes("FROM voiceagent.provider_selections e")) return { rows: environmentSelections };
    if (sql.includes("FROM voiceagent.role_tts_selections")) return { rows: roleTarget ? [{ target: roleTarget }] : [] };
    if (sql.includes("FROM voiceagent.provider_instances") && sql.includes("id = $1::uuid")) return { rows: roleInstance };
    if (sql.includes("FROM voiceagent.provider_instances") && sql.includes("provider = $3")) return { rows: compatibleTts };
    if (sql.includes("COUNT(*) FILTER")) return { rows: [{ asr_count: String(asrCount), tts_count: String(ttsCount) }] };
    return { rows: [] };
  });
}

afterEach(() => {
  vi.clearAllMocks();
  roleLookup.shared.mockReset();
  roleLookup.personal.mockReset();
  vi.unstubAllEnvs();
});

describe("platform speech admission", () => {
  it("uses a role's ASR and LLM provider overrides instead of global selections", async () => {
    roleLookup.shared.mockResolvedValue({ asr_provider: "dashscope", llm_provider: "openai" });
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-asr");
    vi.stubEnv("DOUBAO_API_KEY", "platform-tts");
    vi.stubEnv("OPENAI_API_KEY", "platform-llm");
    setup([], 0, 0, [
      { id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "platform", capability: "asr", provider: "doubao", model: "", display_name: "豆包", key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true },
      { id: "c8135c1c-7989-4a04-aac8-a759ed98213c", scope: "platform", capability: "llm", provider: "deepseek", model: "", display_name: "DeepSeek", key_version: "48ff0333-901c-493a-9766-54a7284cfbd3", enabled: true },
    ]);
    const admission = await admitVoiceSession(null, "doubao", undefined, "role-avatar-test");
    expect(admission.sources.asr.provider).toBe("dashscope");
    expect(admission.sources.llm.provider).toBe("openai");
  });
  it("lets a personal environment choice override the platform instance and legacy personal key", async () => {
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    vi.stubEnv("VOICEAGENT_TTS_BACKEND", "bailian");
    setup([{ provider: "doubao", key_version: "38ff0333-901c-493a-9766-54a7284cfbd1" }], 0, 0,
      [{ id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "platform", capability: "asr",
        provider: "doubao", model: "", display_name: "平台豆包", key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true }],
      [{ capability: "asr", provider: "dashscope", scope: "personal" }]);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" });
    expect(admission.sources.asr).toEqual({ provider: "dashscope", source: "platform" });
    expect(admission.instances?.asr).toBeUndefined();
    const insert = database.client.query.mock.calls.find(([sql]) => (sql as string).includes("INSERT INTO"));
    expect(JSON.parse(insert?.[1]?.[12] as string)).not.toHaveProperty("doubao");
  });
  it("atomically checks independent ASR and TTS slots before reserving", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 0);
    const admission = await admitVoiceSession(null, "dashscope");
    expect(admission.sources.asr.source).toBe("platform");
    expect(admission.sources.tts.source).toBe("platform");
    expect(admission.deadline).not.toBeNull();
    const queries = database.client.query.mock.calls.map(([sql]) => sql as string);
    expect(queries.findIndex((sql) => sql.includes("pg_advisory_xact_lock")))
      .toBeLessThan(queries.findIndex((sql) => sql.includes("COUNT(*) FILTER")));
    expect(queries.findIndex((sql) => sql.includes("COUNT(*) FILTER")))
      .toBeLessThan(queries.findIndex((sql) => sql.includes("INSERT INTO")));
  });

  it("allows a platform TTS session while only the ASR pool is full when ASR is personal", async () => {
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([{ provider: "doubao", key_version: "38ff0333-901c-493a-9766-54a7284cfbd1" }], 1, 0);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope");
    expect(admission.sources.asr.source).toBe("personal");
    expect(admission.sources.tts.source).toBe("platform");
  });

  it("uses the most recently saved personal LLM provider for a new session", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-deepseek");
    setup([
      { provider: "openai", key_version: "38ff0333-901c-493a-9766-54a7284cfbd1" },
      { provider: "deepseek", key_version: "48ff0333-901c-493a-9766-54a7284cfbd2" },
    ], 0, 0);

    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope");
    expect(admission.sources.llm).toEqual({ provider: "openai", source: "personal" });
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("ORDER BY updated_at DESC"))).toBe(true);
  });

  it("rejects a full required speech pool without issuing a ticket", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 1);
    await expect(admitVoiceSession(null, "dashscope")).rejects.toMatchObject({
      code: "speech_capacity_full", status: 429,
    } satisfies Partial<VoiceAdmissionError>);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
    expect(database.client.query.mock.calls.some(([sql]) => sql === "ROLLBACK")).toBe(true);
  });

  it("pins an explicitly selected instance and does not substitute a saved legacy key", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    const id = "c8135c1c-7989-4a04-aac8-a759ed98213b";
    setup([{ provider: "deepseek", key_version: "38ff0333-901c-493a-9766-54a7284cfbd1" }], 0, 0,
      [{ id, scope: "personal", capability: "llm", provider: "openai", model: "gpt-4.1-mini",
        display_name: "我的 OpenAI",
        key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true }]);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" });
    expect(admission.sources.llm).toEqual({ provider: "openai", source: "personal", instanceName: "我的 OpenAI" });
    expect(admission.instances?.llm).toBe(id);
    const insert = database.client.query.mock.calls.find(([sql]) => (sql as string).includes("INSERT INTO"));
    expect(JSON.parse(insert?.[1]?.[13] as string).llm).toEqual({ id, scope: "personal",
      version: "48ff0333-901c-493a-9766-54a7284cfbd2", provider: "openai", model: "gpt-4.1-mini" });
  });

  it("fails closed when the selected instance is disabled", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 0, [{ id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "personal",
      capability: "asr", provider: "doubao", model: "", display_name: "已停用",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2",
      enabled: false }]);
    await expect(admitVoiceSession({ issuer: "issuer", subject: "person" })).rejects.toMatchObject({
      code: "configuration_invalid", status: 409,
    });
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
  });

  it("fails closed when a selected speech instance has not passed its realtime contract", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 0, [{ id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "personal",
      capability: "tts", provider: "dashscope", model: "", display_name: "未通过的百炼",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true,
      connection_status: "failed" }]);
    await expect(admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope"))
      .rejects.toMatchObject({ code: "configuration_invalid", status: 409 });
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
  });

  it("uses a platform default for guest sessions without requiring an environment key for that capability", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "");
    vi.stubEnv("OPENAI_API_KEY", "");
    setup([], 0, 0, [{ id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "platform",
      capability: "llm", provider: "openai", model: "gpt-selected", display_name: "平台 OpenAI",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true }]);
    const admission = await admitVoiceSession(null);
    expect(admission.sources.llm).toEqual({ provider: "openai", source: "platform", instanceName: "平台 OpenAI" });
    expect(admission.instances?.llm).toBe("c8135c1c-7989-4a04-aac8-a759ed98213b");
  });

  it("uses a compatible tested personal TTS instance for a role without changing the global default", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    const defaultInstance = { id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "personal" as const,
      capability: "tts" as const, provider: "doubao", model: "", display_name: "豆包语音",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true };
    const compatible = { ...defaultInstance, id: "d8135c1c-7989-4a04-aac8-a759ed98213b",
      provider: "dashscope", display_name: "我的百炼" };
    setup([], 0, 0, [defaultInstance], [], [compatible]);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope");
    expect(admission.sources.tts).toEqual({ provider: "dashscope", source: "personal", instanceName: "我的百炼" });
    expect(admission.instances?.tts).toBe(compatible.id);
  });

  it("falls back to the role provider's platform key when no compatible instance exists", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 0, [{ id: "c8135c1c-7989-4a04-aac8-a759ed98213b", scope: "personal",
      capability: "tts", provider: "doubao", model: "", display_name: "豆包语音",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true }]);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope");
    expect(admission.sources.tts).toEqual({ provider: "dashscope", source: "platform" });
    expect(admission.instances?.tts).toBeUndefined();
  });

  it("pins the personal TTS configuration chosen for this user's role", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    const chosen = { id: "b8135c1c-7989-4a04-aac8-a759ed98213b", scope: "personal" as const,
      capability: "tts" as const, provider: "dashscope", model: "", display_name: "我的百炼 B",
      key_version: "48ff0333-901c-493a-9766-54a7284cfbd2", enabled: true, connection_status: "passed" as const };
    setup([], 0, 0, [], [], [], chosen.id, [chosen]);
    const admission = await admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope", undefined, "role-avatar-test");
    expect(admission.sources.tts).toEqual({ provider: "dashscope", source: "personal", instanceName: "我的百炼 B" });
    expect(admission.instances?.tts).toBe(chosen.id);
    const query = database.client.query.mock.calls.find(([sql]) => (sql as string).includes("FROM voiceagent.role_tts_selections"));
    expect(query?.[1]).toEqual(["issuer", "person", "role-avatar-test"]);
  });

  it("rejects an unavailable role-specific instance instead of silently using another key", async () => {
    vi.stubEnv("DOUBAO_API_KEY", "platform-doubao");
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-dashscope");
    vi.stubEnv("DEEPSEEK_API_KEY", "platform-llm");
    setup([], 0, 0, [], [], [], "b8135c1c-7989-4a04-aac8-a759ed98213b");
    await expect(admitVoiceSession({ issuer: "issuer", subject: "person" }, "dashscope", undefined, "role-avatar-test"))
      .rejects.toMatchObject({ code: "configuration_invalid", status: 409 });
  });
});
