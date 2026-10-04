import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { deleteConversation, getConversation, listConversations, renameConversation, saveConversation } from "./conversation-history";

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
  it("preserves the thread through continuation and rejects role or thread changes", async () => {
    const directory = await root();
    const input = { id: "1c45d57b-541e-41f9-a432-f121036dc443", roleId: "role-a", roleName: "助手", mode: "conversation", entries: [{ role: "user", text: "继续" }], ended: false, threadId: "thread-one", voiceSessionId: "voice-one" };
    await saveConversation("alice", input, directory);
    const updated = await saveConversation("alice", { ...input, voiceSessionId: "voice-two" }, directory);
    expect(updated).toMatchObject({ thread_id: "thread-one", voice_session_id: "voice-two" });
    await expect(saveConversation("alice", { ...input, roleId: "role-b" }, directory)).rejects.toThrow("对话身份无效");
    await expect(saveConversation("alice", { ...input, threadId: "thread-other" }, directory)).rejects.toThrow("对话身份无效");
    await expect(saveConversation("alice", { ...input, voiceSessionId: null }, directory)).rejects.toThrow("会话信息无效");
    expect(await getConversation("bob", input.id, directory)).toBeNull();
  });
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
  it("preserves a custom title through continuation and isolates renaming by owner", async () => {
    const directory = await root();
    const input = { id: "1c45d57b-541e-41f9-a432-f121036dc443", roleId: "role-a", roleName: "助手", mode: "conversation", entries: [{ role: "user", text: "你好" }], ended: false, threadId: "thread-one", voiceSessionId: "voice-one" };
    const original = await saveConversation("alice", input, directory);
    expect(await renameConversation("bob", input.id, "别人的名字", directory)).toBeNull();
    await expect(renameConversation("alice", input.id, "  ", directory)).rejects.toThrow("对话名称");
    await expect(renameConversation("alice", input.id, "名字\n换行", directory)).rejects.toThrow("对话名称");
    await expect(renameConversation("alice", input.id, "名".repeat(81), directory)).rejects.toThrow("对话名称");
    const renamed = await renameConversation("alice", input.id, "  北京天气与生日  ", directory);
    expect(renamed).toMatchObject({ title: "北京天气与生日", updated_at: original.updated_at, entries: original.entries, thread_id: original.thread_id });
    const continued = await saveConversation("alice", { ...input, entries: [...input.entries, { role: "assistant", text: "你好呀" }] }, directory);
    expect(continued.title).toBe("北京天气与生日");
    expect((await listConversations("alice", directory))[0].title).toBe("北京天气与生日");
    expect(await deleteConversation("alice", input.id, directory)).toBe(true);
  });

});
