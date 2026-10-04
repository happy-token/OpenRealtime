import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST, PATCH, DELETE } from "./route";

vi.mock("@/lib/conversation-history-auth", () => ({ conversationOwner: async (request: Request) =>
  request.headers.get("x-test-owner") === "denied" ? Response.json({}, { status: 401 })
    : request.headers.get("x-test-owner") || "alice" }));
vi.mock("@/lib/memory-role", () => ({ memoryRoleForRequest: async (_request: Request, id: string) =>
  ["role-a", "role-b"].includes(id) ? { role_id: id, memory_enabled: false } : null }));
let directory: string;
beforeEach(async () => { directory = await mkdtemp(path.join(tmpdir(), "memory-api-")); vi.stubEnv("VOICEAGENT_MEMORY_DIR", directory); });
afterEach(async () => { vi.unstubAllEnvs(); await rm(directory, { recursive: true, force: true }); });
function request(method: string, body?: object, owner = "alice", role = "role-a", id?: string) {
  return new Request(`https://app.example/api/memory?roleId=${role}${id ? `&id=${id}` : ""}`, {
    method, headers: { "Content-Type": "application/json", "x-test-owner": owner },
    body: body ? JSON.stringify(body) : undefined,
  });
}
describe("memory management API", () => {
  it("allows preparing and editing memory while automatic use is disabled", async () => {
    const response = await POST(request("POST", { kind: "goal", content: "学习日语" }));
    expect(response.status).toBe(201);
    const { memory } = await response.json();
    expect((await PATCH(request("PATCH", { id: memory.id, content: "学习法语" }))).status).toBe(200);
    expect((await (await GET(request("GET"))).json()).memories[0].content).toBe("学习法语");
    expect((await DELETE(request("DELETE", undefined, "alice", "role-a", memory.id))).status).toBe(200);
    expect((await (await GET(request("GET"))).json()).memories).toEqual([]);
  });
  it("clear only affects the selected owner and role", async () => {
    for (const [owner, role] of [["alice", "role-a"], ["alice", "role-b"], ["bob", "role-a"]]) {
      await POST(request("POST", { kind: "goal", content: "学习日语" }, owner, role));
    }
    await DELETE(request("DELETE"));
    expect((await (await GET(request("GET"))).json()).memories).toHaveLength(0);
    expect((await (await GET(request("GET", undefined, "bob"))).json()).memories).toHaveLength(1);
    expect((await (await GET(request("GET", undefined, "alice", "role-b"))).json()).memories).toHaveLength(1);
  });
  it("rejects unauthorized requests, unknown roles and sensitive content", async () => {
    expect((await POST(request("POST", { kind: "goal", content: "学习日语" }, "denied"))).status).toBe(401);
    expect((await GET(request("GET", undefined, "alice", "missing"))).status).toBe(404);
    expect((await POST(request("POST", { kind: "goal", content: "密码是123456" }))).status).toBe(400);
  });
});
