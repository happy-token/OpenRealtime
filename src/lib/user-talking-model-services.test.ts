import { beforeEach, describe, expect, it, vi } from "vitest";

const database = vi.hoisted(() => ({ rows: new Map<string, { url: string; sealed_token: Buffer | null }>() }));
vi.mock("./user-db", () => ({
  userTable: () => '"voiceagent"."user_talking_model_services"',
  userDatabase: () => ({ query: async (sql: string, values: unknown[]) => {
    const key = `${values[0]}:${values[1]}:${values[2]}`;
    if (sql.startsWith("INSERT")) {
      database.rows.set(key, { url: values[3] as string, sealed_token: values[4] as Buffer | null });
      return { rows: [] };
    }
    if (sql.startsWith("DELETE")) { database.rows.delete(key); return { rows: [] }; }
    if (values.length === 2) return { rows: [...database.rows.entries()].filter(([name]) => name.startsWith(`${values[0]}:${values[1]}:`)).map(([name, row]) => ({ kind: name.split(":").at(-1), ...row })) };
    return { rows: database.rows.has(key) ? [database.rows.get(key)] : [] };
  } }),
}));

import { deleteUserTalkingService, listUserTalkingServices, loadUserTalkingService, saveUserTalkingService } from "./user-talking-model-services";

const alice = { issuer: "issuer", subject: "alice" };
const bob = { issuer: "issuer", subject: "bob" };

describe("user talking model services", () => {
  beforeEach(() => {
    database.rows.clear();
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 7).toString("base64url"));
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", "https://models.example");
  });

  it("encrypts tokens and isolates user and model kind", async () => {
    await saveUserTalkingService(alice, "musetalk", "https://models.example", "alice-token");
    await saveUserTalkingService(bob, "musetalk", "https://models.example", "bob-token");
    await saveUserTalkingService(alice, "wav2lip", "https://models.example", "wav-token");
    expect(await loadUserTalkingService(alice, "musetalk")).toEqual({ url: "https://models.example", token: "alice-token" });
    expect(await loadUserTalkingService(bob, "musetalk")).toEqual({ url: "https://models.example", token: "bob-token" });
    expect((await listUserTalkingServices(alice)).wav2lip?.token).toBe("wav-token");
    expect(database.rows.get("issuer:alice:musetalk")?.sealed_token?.toString()).not.toContain("alice-token");
    await deleteUserTalkingService(alice, "musetalk");
    expect(await loadUserTalkingService(alice, "musetalk")).toBeNull();
    expect(await loadUserTalkingService(bob, "musetalk")).not.toBeNull();
  });

  it("cannot decrypt a token copied to another user or model kind", async () => {
    await saveUserTalkingService(alice, "musetalk", "https://models.example", "secret");
    const row = database.rows.get("issuer:alice:musetalk");
    database.rows.set("issuer:bob:musetalk", row!);
    database.rows.set("issuer:alice:wav2lip", row!);
    await expect(loadUserTalkingService(bob, "musetalk")).rejects.toThrow();
    await expect(loadUserTalkingService(alice, "wav2lip")).rejects.toThrow();
  });
});
