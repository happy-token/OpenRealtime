import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ actor: vi.fn(), list: vi.fn(), create: vi.fn() }));
vi.mock("@/lib/provider-instance-access", () => ({ providerActor: state.actor }));
vi.mock("@/lib/user-provider-credentials", () => ({ listPersonalKeyStatuses: vi.fn(async () => []) }));
vi.mock("@/lib/provider-instances", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/provider-instances")>();
  return { ...original, listProviderInstances: state.list, createProviderInstance: state.create };
});

import { GET, POST } from "./route";

const input = { scope: "personal", capability: "asr", provider: "doubao",
  displayName: "豆包 A", model: "", apiKey: "key-12345678" };

function request(method: "GET" | "POST", body?: object, origin = "https://app.test") {
  return new NextRequest("https://app.test/api/provider-instances", { method,
    headers: { origin, "content-type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}) });
}

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });

describe("provider instance collection API", () => {
  it("requires authentication and rejects cross-origin mutation", async () => {
    state.actor.mockResolvedValue(null);
    expect((await GET(request("GET"))).status).toBe(401);
    expect((await POST(request("POST", input))).status).toBe(401);
    state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
    expect((await POST(request("POST", input, "https://evil.test"))).status).toBe(403);
    expect(state.create).not.toHaveBeenCalled();
  });

  it("allows a user's own built-in instance but refuses platform writes and Bella ASR", async () => {
    const user = { issuer: "issuer", subject: "alice" };
    state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
    state.create.mockResolvedValue({ id: "id", scope: "personal" });
    expect((await POST(request("POST", input))).status).toBe(201);
    expect(state.create).toHaveBeenCalledWith(user, "personal", expect.objectContaining({ provider: "doubao" }));
    expect((await POST(request("POST", { ...input, scope: "platform" }))).status).toBe(403);
    expect((await POST(request("POST", { ...input, provider: "bella" }))).status).toBe(400);
    expect(state.create).toHaveBeenCalledTimes(1);
  });

  it("returns only the repository's masked public projection", async () => {
    state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
    state.list.mockResolvedValue({ instances: [{ id: "id", keySuffix: "3456" }], selections: {} });
    vi.stubEnv("DOUBAO_API_KEY", "private-doubao-9876");
    const response = await GET(request("GET"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ instances: [{ keySuffix: "3456" }], platformCredentials: [
      { capability: "asr", provider: "doubao", keySuffix: "9876" },
      { capability: "tts", provider: "doubao", keySuffix: "9876" },
    ] });
    expect(JSON.stringify(body)).not.toContain("private-doubao");
  });
});
