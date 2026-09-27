import { afterEach, describe, expect, it, vi } from "vitest";

const database = vi.hoisted(() => ({ query: vi.fn(), client: { query: vi.fn(), release: vi.fn() }, connect: vi.fn() }));
vi.mock("./user-db", () => ({ userDatabase: () => ({ query: database.query, connect: database.connect }),
  userTable: (name: string) => `voiceagent.${name}` }));

import { claimProviderConnectionTest, createProviderInstance, deleteProviderInstance, parseBuiltinProvider, ProviderInstanceQuotaError,
  ProviderInstanceNotReadyError, selectPlatformEnvironmentProvider, selectProviderInstance, validateProviderInstanceInput } from "./provider-instances";

const user = { issuer: "issuer", subject: "alice" };
const id = "d7952389-59d1-4a4d-9d89-9642d851544b";

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });

describe("provider instances", () => {
  it("selects only a configured official platform environment provider without copying its key", async () => {
    vi.stubEnv("DASHSCOPE_API_KEY", "platform-secret-1234");
    database.query.mockResolvedValue({ rowCount: 1, rows: [] });
    await expect(selectPlatformEnvironmentProvider(user, "asr", "dashscope")).resolves.toBe(true);
    const [sql, values] = database.query.mock.calls.at(-1)!;
    expect(sql).toContain("instance_id, env_provider");
    expect(values).toEqual(["personal", "issuer", "alice", "asr", "dashscope"]);
    expect(JSON.stringify(database.query.mock.calls)).not.toContain("platform-secret-1234");
    await expect(selectPlatformEnvironmentProvider(user, "llm", "dashscope")).resolves.toBe(false);
  });
  it("only admits the built-in provider for its declared capability", () => {
    expect(parseBuiltinProvider("doubao", "asr")).toBe("doubao");
    expect(parseBuiltinProvider("dashscope", "asr")).toBe("dashscope");
    expect(parseBuiltinProvider("bella", "asr")).toBeNull();
    expect(parseBuiltinProvider("openai", "asr")).toBeNull();
    expect(validateProviderInstanceInput({ capability: "tts", provider: "doubao",
      displayName: "语音 A", model: "", apiKey: "12345678" })).toMatchObject({ provider: "doubao" });
    expect(validateProviderInstanceInput({ capability: "tts", provider: "doubao",
      displayName: "语音 A", model: "unsupported-model", apiKey: "12345678" })).toBeNull();
    expect(validateProviderInstanceInput({ capability: "llm", provider: "openai",
      displayName: "模型", model: "", baseUrl: "http://127.0.0.1:8000", apiKey: "12345678" })).toBeNull();
    expect(validateProviderInstanceInput({ capability: "llm", provider: "openai",
      displayName: "模型", model: "gpt-test", apiKey: "12345678" }, true)).toBeNull();
  });

  it("encrypts a new instance key and never returns it in public instance JSON", async () => {
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 7).toString("base64url"));
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("COUNT(*)")
      ? { rows: [{ count: "0" }] } : sql.includes("INSERT INTO") ? { rows: [{ id, scope: "personal", capability: "llm", provider: "openai",
      display_name: "模型 A", model: "gpt-test", enabled: true, key_suffix: "abcd", key_version: id,
      connection_status: "untested", tested_at: null, test_message: null, updated_at: new Date() }] }
        : { rows: [] });
    const instance = await createProviderInstance(user, "personal", { capability: "llm", provider: "openai",
      displayName: "模型 A", model: "gpt-test", apiKey: "secret-abcd" });
    const parameters = database.client.query.mock.calls.find(([sql]) => (sql as string).includes("INSERT INTO"))?.[1] as unknown[];
    expect(parameters[2]).toBe("issuer");
    expect(parameters[3]).toBe("alice");
    expect(Buffer.isBuffer(parameters[9])).toBe(true);
    expect((parameters[9] as Buffer).includes(Buffer.from("secret-abcd"))).toBe(false);
    expect(JSON.stringify(instance)).not.toContain("secret-abcd");
    expect(instance.keySuffix).toBe("abcd");
  });

  it("enforces a serialized per-capability instance limit", async () => {
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 7).toString("base64url"));
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("COUNT(*)")
      ? { rows: [{ count: "50" }] } : { rows: [] });
    await expect(createProviderInstance(user, "personal", { capability: "llm", provider: "openai",
      displayName: "too many", model: "", apiKey: "secret-key" })).rejects.toBeInstanceOf(ProviderInstanceQuotaError);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("pg_advisory_xact_lock"))).toBe(true);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
  });

  it("checks ownership and enabled state before saving a selection", async () => {
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("SELECT id")
      ? { rows: [], rowCount: 0 } : { rows: [], rowCount: 0 });
    await expect(selectProviderInstance(user, id)).resolves.toBeNull();
    const select = database.client.query.mock.calls.find(([sql]) => (sql as string).includes("FOR SHARE"));
    expect(select?.[0]).toContain("issuer = $2 AND subject = $3");
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
  });

  it("refuses to select an instance whose realtime contract has not passed", async () => {
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("SELECT id")
      ? { rows: [{ id, scope: "personal", capability: "tts", provider: "dashscope", enabled: true,
        connection_status: "failed" }], rowCount: 1 } : { rows: [], rowCount: 0 });
    await expect(selectProviderInstance(user, id)).rejects.toBeInstanceOf(ProviderInstanceNotReadyError);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("INSERT INTO"))).toBe(false);
  });

  it("refuses to delete an instance selected by any user", async () => {
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("SELECT id")
      || sql.includes("SELECT 1") ? { rows: [{}], rowCount: 1 } : { rows: [], rowCount: 0 });
    await expect(deleteProviderInstance(user, "personal", id)).rejects.toThrow("请先切换");
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).startsWith("DELETE"))).toBe(false);
    expect(database.client.query.mock.calls.some(([sql]) => sql === "ROLLBACK")).toBe(true);
  });

  it("refuses to delete an instance selected by a role", async () => {
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => {
      if (sql.includes("SELECT id FROM")) return { rows: [{ id }], rowCount: 1 };
      if (sql.includes("FROM voiceagent.role_tts_selections")) return { rows: [{}], rowCount: 1 };
      return { rows: [], rowCount: 0 };
    });
    await expect(deleteProviderInstance(user, "personal", id)).rejects.toThrow("请先切换角色");
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).startsWith("DELETE"))).toBe(false);
    expect(database.client.query.mock.calls.some(([sql]) => sql === "ROLLBACK")).toBe(true);
  });

  it("serializes billable tests and limits all of one owner's instances together", async () => {
    database.connect.mockResolvedValue(database.client);
    database.client.query.mockImplementation(async (sql: string) => sql.includes("COUNT(*)")
      ? { rows: [{ count: "3" }] } : { rows: [], rowCount: 0 });
    await expect(claimProviderConnectionTest(user, "personal", id, id)).resolves.toBe(false);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("pg_advisory_xact_lock"))).toBe(true);
    expect(database.client.query.mock.calls.some(([sql]) => (sql as string).includes("SET test_last_started_at"))).toBe(false);
  });
});
