import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { deleteConversation, getConversation, listConversations, saveConversation } from "./conversation-history";

const roots: string[] = [];
afterEach(async () => {
  delete process.env.VOICEAGENT_CONVERSATION_RETENTION_DAYS;
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function root() {
  const value = await mkdtemp(path.join(tmpdir(), "openrealtime-conversations-"));
  roots.push(value);
  return value;
}

describe("conversation history", () => {
  it("keeps conversations isolated by owner and supports deletion", async () => {
    const directory = await root();
    const id = "1c45d57b-541e-41f9-a432-f121036dc441";
    const input = { id, roleId: "role-a", roleName: "助手", mode: "conversation", entries: [{ role: "user" as const, text: "你好" }], ended: false };
    await saveConversation("alice", input, directory);
    expect((await listConversations("alice", directory))[0]).toMatchObject({ id, title: "你好", entry_count: 1 });
    expect(await listConversations("bob", directory)).toEqual([]);
    expect(await getConversation("bob", id, directory)).toBeNull();
    expect(await deleteConversation("bob", id, directory)).toBe(false);
    await expect(saveConversation("bob", input, directory)).rejects.toThrow("对话 ID 已被使用");
    expect(await deleteConversation("alice", id, directory)).toBe(true);
    expect(await getConversation("alice", id, directory)).toBeNull();
  });

  it("updates one conversation and records its end", async () => {
    const directory = await root();
    const id = "1c45d57b-541e-41f9-a432-f121036dc442";
    const base = { id, roleId: null, roleName: "默认助手", mode: "conversation" };
    const first = await saveConversation("alice", { ...base, entries: [{ role: "user", text: "第一句" }], ended: false }, directory);
    const last = await saveConversation("alice", { ...base, entries: [{ role: "user", text: "第一句" }, { role: "assistant", text: "答复" }], ended: true }, directory);
    expect(last.started_at).toBe(first.started_at);
    expect(last.ended_at).not.toBeNull();
    expect(last.entries).toHaveLength(2);
    expect(await listConversations("alice", directory)).toHaveLength(1);
  });
});
