import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { getConversation, saveConversation } from "@/lib/conversation-history";
import { PATCH, DELETE } from "./route";
const { owner } = vi.hoisted(() => ({ owner: vi.fn() }));
vi.mock("@/lib/conversation-history-auth", () => ({ conversationOwner: owner }));
let root: string;
const id = "1c45d57b-541e-41f9-a432-f121036dc443";
const context = { params: Promise.resolve({ conversationId: id }) };
beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "history-api-"));
  vi.stubEnv("CONVERSATION_HISTORY_DIR", root);
  owner.mockReset().mockResolvedValue("alice");
  await saveConversation("alice", { id, roleId: null, roleName: "助手", mode: "conversation", entries: [{ role: "user", text: "你好" }], ended: true });
});
afterEach(async () => { vi.unstubAllEnvs(); await rm(root, { recursive: true, force: true }); });
function request(title: unknown) { return new Request(`http://localhost/api/conversations/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }); }
describe("conversation rename and delete API", () => {
  it("renames and deletes an owned conversation through authenticated writes", async () => {
    const response = await PATCH(request("天气查询"), context);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ title: "天气查询" });
    expect(owner).toHaveBeenCalledWith(expect.any(Request), true);
    expect((await getConversation("alice", id))?.title).toBe("天气查询");
    expect((await DELETE(new Request(`http://localhost/api/conversations/${id}`, { method: "DELETE" }), context)).status).toBe(200);
    expect(await getConversation("alice", id)).toBeNull();
  });
  it("rejects invalid titles and changes to other owners' records", async () => {
    for (const title of ["", " ", "a\nb", "名".repeat(81), 123]) expect((await PATCH(request(title), context)).status).toBe(400);
    owner.mockResolvedValue("bob");
    expect((await PATCH(request("替换"), context)).status).toBe(404);
    expect((await DELETE(new Request(`http://localhost/api/conversations/${id}`, { method: "DELETE" }), context)).status).toBe(404);
    expect((await getConversation("alice", id))?.title).toBe("你好");
  });
});
