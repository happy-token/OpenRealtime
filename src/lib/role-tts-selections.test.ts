import { afterEach, describe, expect, it, vi } from "vitest";

const database = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("./user-db", () => ({ userDatabase: () => database, userTable: (name: string) => `voiceagent.${name}` }));

import { getRoleTtsTarget, isRoleTtsTarget, resolveRoleTtsTarget, saveRoleTtsTarget } from "./role-tts-selections";

const user = { issuer: "issuer", subject: "alice" };
const id = "b8135c1c-7989-4a04-aac8-a759ed98213b";

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });

describe("role TTS selections", () => {
  it("accepts only an official environment provider or a UUID instance", () => {
    expect(isRoleTtsTarget("env:dashscope")).toBe(true);
    expect(isRoleTtsTarget(id)).toBe(true);
    expect(isRoleTtsTarget("env:evil")).toBe(false);
    expect(isRoleTtsTarget("../key")).toBe(false);
  });

  it("validates an instance against the user's ownership and realtime test state", async () => {
    database.query.mockResolvedValue({ rows: [{ provider: "dashscope", scope: "personal" }] });
    await expect(resolveRoleTtsTarget(user, id)).resolves.toEqual({ provider: "dashscope", scope: "personal" });
    const [sql, values] = database.query.mock.calls[0];
    expect(sql).toContain("connection_status = 'passed'");
    expect(sql).toContain("issuer = $2 AND subject = $3");
    expect(values).toEqual([id, "issuer", "alice"]);
    database.query.mockResolvedValueOnce({ rows: [] });
    await expect(resolveRoleTtsTarget(user, id)).resolves.toBeNull();
  });

  it("stores a role choice only for the current user", async () => {
    database.query.mockResolvedValue({ rows: [{ target: id }] });
    await saveRoleTtsTarget(user, "role-avatar-test", id);
    expect(database.query.mock.calls[0][1]).toEqual(["issuer", "alice", "role-avatar-test", id]);
    await expect(getRoleTtsTarget(user, "role-avatar-test")).resolves.toBe(id);
    expect(database.query.mock.calls[1][1]).toEqual(["issuer", "alice", "role-avatar-test"]);
  });
});
