import { randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import { listMemories } from "@/lib/memory-catalog";

vi.mock("@/lib/conversation-history-auth", () => ({ conversationOwner: async () => "alice" }));
vi.mock("@/lib/memory-role", () => ({ memoryRoleForRequest: async (_request: Request, id: string) => ({ role_id: id, memory_enabled: id === "role-enabled" }) }));
let directory: string;
beforeEach(async () => { directory = await mkdtemp(path.join(tmpdir(), "birthday-extraction-")); vi.stubEnv("VOICEAGENT_MEMORY_DIR", path.join(directory, "memory")); vi.stubEnv("CONVERSATION_HISTORY_DIR", path.join(directory, "conversations")); });
afterEach(async () => { vi.unstubAllEnvs(); await rm(directory, { recursive: true, force: true }); });
function request(roleId: string, id: string, role = "user", isFinal = true) {
  return new Request("https://app.example/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, roleId, roleName: "若水", mode: "conversation", ended: false, entries: [{ id: "birthday-turn", role, text: "呃。你能不能记住我的生日？我的生日是10月。18号。", isFinal }] }) });
}
describe("birthday conversation persistence", () => {
  it("persists an explicit birthday with its source once and keeps owner and role isolated", async () => {
    const id = randomUUID();
    expect((await POST(request("role-enabled", id))).status).toBe(200);
    expect((await POST(request("role-enabled", id))).status).toBe(200);
    const memories = await listMemories("alice", "role-enabled");
    expect(memories).toHaveLength(1);
    expect(memories[0]).toMatchObject({ kind: "fact", content: "我的生日是10月18日", source_conversation_id: id });
    expect(await listMemories("bob", "role-enabled")).toEqual([]);
    expect(await listMemories("alice", "role-disabled")).toEqual([]);
  });
  it("does not extract when disabled, from assistant messages, or from partial ASR", async () => {
    for (const req of [request("role-disabled", randomUUID()), request("role-enabled", randomUUID(), "assistant"), request("role-enabled", randomUUID(), "user", false)]) {
      expect((await POST(req)).status).toBe(200);
    }
    expect(await listMemories("alice", "role-disabled")).toEqual([]);
    expect(await listMemories("alice", "role-enabled")).toEqual([]);
  });
});
