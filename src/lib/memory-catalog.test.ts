import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { addMemory, extractMemories, listMemories, removeMemory, updateMemory } from "./memory-catalog";

const roots: string[] = [];
afterEach(async () => { await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true }))); });
async function root() { const value = await mkdtemp(path.join(tmpdir(), "openrealtime-memory-")); roots.push(value); return value; }

describe("Memory", () => {
  it("isolates by owner and role and supports edit and clear", async () => {
    const directory = await root();
    const item = await addMemory("alice", "role-a", "preference", "我喜欢简洁回答", null, directory);
    expect(await listMemories("alice", "role-a", directory)).toHaveLength(1);
    expect(await listMemories("bob", "role-a", directory)).toEqual([]);
    expect(await listMemories("alice", "role-b", directory)).toEqual([]);
    expect(await updateMemory("bob", "role-a", item.id, "我喜欢详细回答", directory)).toBeNull();
    expect((await updateMemory("alice", "role-a", item.id, "我喜欢详细回答", directory))?.content).toBe("我喜欢详细回答");
    expect(await removeMemory("alice", "role-a", null, directory)).toBe(true);
    expect(await listMemories("alice", "role-a", directory)).toEqual([]);
  });

  it("extracts only explicit categories and rejects sensitive content", async () => {
    expect(extractMemories("我喜欢简洁回答")).toEqual([{ kind: "preference", content: "我喜欢简洁回答" }]);
    expect(extractMemories("我的目标是学会日语")).toEqual([{ kind: "goal", content: "我的目标是学会日语" }]);
    expect(extractMemories("我的手机号是13800138000")).toEqual([]);
    const directory = await root();
    await expect(addMemory("alice", "role-a", "preference", "我的邮箱是a@example.com", null, directory)).rejects.toThrow("敏感信息");
  });
});
