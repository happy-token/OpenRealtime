import { afterEach, describe, expect, it, vi } from "vitest";

const database = vi.hoisted(() => ({
  client: { query: vi.fn(), release: vi.fn() },
  connect: vi.fn(),
}));
vi.mock("./user-db", () => ({
  userDatabase: () => ({ connect: database.connect }),
  userTable: (name: string) => `voiceagent.${name}`,
}));

import { admitVoiceSession, VoiceAdmissionError } from "./voice-admission";

function setup(versions: { provider: string; key_version: string }[], asrCount: number, ttsCount: number) {
  database.connect.mockResolvedValue(database.client);
  database.client.query.mockImplementation(async (sql: string) => {
    if (sql.includes("SELECT provider, key_version")) return { rows: versions };
    if (sql.includes("COUNT(*) FILTER")) return { rows: [{ asr_count: String(asrCount), tts_count: String(ttsCount) }] };
    return { rows: [] };
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("platform speech admission", () => {
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
});
