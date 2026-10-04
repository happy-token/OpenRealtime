import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, PUT } from "./route";

vi.mock("@/lib/user-session", () => ({ userFromRequest: async (request: Request) => request.headers.get("x-test-user") ? { issuer: "test", subject: request.headers.get("x-test-user") } : null }));
vi.mock("@/lib/knowledge-role-scope", () => ({ requireKnowledgeRole: async (_request: Request, roleId: string) => roleId === "role-a" ? roleId : Response.json({}, { status: 404 }) }));
let root: string;
beforeEach(async () => { root = await mkdtemp(path.join(tmpdir(), "tool-permission-api-")); vi.stubEnv("VOICEAGENT_TOOL_PERMISSIONS_DIR", root); });
afterEach(async () => { vi.unstubAllEnvs(); await rm(root, { recursive: true, force: true }); });
function request(method: string, body?: object, user = "alice", origin = "https://app.example") {
  return new Request("https://app.example/api/tool-permissions", { method, headers: { "Content-Type": "application/json", "x-test-user": user, Origin: origin }, body: body ? JSON.stringify(body) : undefined });
}
describe("tool permission API", () => {
  it("saves global and role settings for the authenticated owner only", async () => {
    expect((await (await GET(request("GET"))).json()).mode).toBe("full");
    expect((await PUT(request("PUT", { mode: "balanced", ownerId: "test#bob" }))).status).toBe(200);
    expect((await PUT(request("PUT", { mode: "confirm", roleId: "role-a" }))).status).toBe(200);
    expect((await (await GET(request("GET"))).json()).roleOverrides).toEqual({ "role-a": "confirm" });
    expect((await (await GET(request("GET", undefined, "bob"))).json()).mode).toBe("full");
    expect((await PUT(request("PUT", { mode: null, roleId: "role-a" }))).status).toBe(200);
    expect((await (await GET(request("GET"))).json()).roleOverrides).toEqual({});
  });
  it("rejects cross-origin mutations and malformed or unknown role modes", async () => {
    expect((await PUT(request("PUT", { mode: "full" }, "alice", "https://evil.example"))).status).toBe(403);
    expect((await PUT(request("PUT", { mode: "other" }))).status).toBe(400);
    expect((await PUT(request("PUT", { mode: null }))).status).toBe(400);
    expect((await PUT(request("PUT", { mode: "full", roleId: "missing" }))).status).toBe(404);
    expect((await PUT(request("PUT", { mode: null, roleId: "missing" }))).status).toBe(200);
    expect((await PUT(request("PUT", { mode: "full", padding: "x".repeat(3000) }))).status).toBe(400);
  });
});
