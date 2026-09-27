import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ actor: vi.fn(), select: vi.fn(), clear: vi.fn() }));
vi.mock("@/lib/provider-instance-access", () => ({ providerActor: state.actor }));
vi.mock("@/lib/provider-instances", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/provider-instances")>();
  return { ...original, selectPlatformEnvironmentProvider: state.select, clearProviderSelection: state.clear };
});

import { DELETE, POST } from "./route";

const user = { issuer: "issuer", subject: "alice" };
const params = { params: Promise.resolve({ capability: "asr" }) };
function request(method: "POST" | "DELETE", origin = "https://app.test", body?: object, query = "") {
  return new NextRequest(`https://app.test/api/provider-selections/asr${query}`, { method,
    headers: { origin, "content-type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}) });
}

afterEach(() => { vi.clearAllMocks(); });

describe("platform environment provider selection API", () => {
  it("requires a signed-in owner and same-origin mutation", async () => {
    state.actor.mockResolvedValue(null);
    expect((await POST(request("POST", undefined, { provider: "doubao" }), params)).status).toBe(401);
    state.actor.mockResolvedValue({ user, signedIn: false, admin: false });
    expect((await POST(request("POST", undefined, { provider: "doubao" }), params)).status).toBe(401);
    state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
    expect((await POST(request("POST", "https://evil.test", { provider: "doubao" }), params)).status).toBe(403);
    expect(state.select).not.toHaveBeenCalled();
  });

  it("validates capability/provider and platform-admin scope", async () => {
    state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
    expect((await POST(request("POST", undefined, { provider: "openai" }), params)).status).toBe(400);
    expect((await POST(request("POST", undefined, { provider: "doubao" }, "?scope=platform"), params)).status).toBe(403);
    expect(state.select).not.toHaveBeenCalled();
  });

  it("selects only a configured provider and never returns its key", async () => {
    state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
    state.select.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    expect((await POST(request("POST", undefined, { provider: "doubao" }), params)).status).toBe(404);
    const response = await POST(request("POST", undefined, { provider: "doubao" }), params);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ selected: true });
    expect(state.select).toHaveBeenLastCalledWith(user, "asr", "doubao", "personal");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("clears only the caller's selection", async () => {
    state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
    state.clear.mockResolvedValue(true);
    const response = await DELETE(request("DELETE"), params);
    expect(response.status).toBe(200);
    expect(state.clear).toHaveBeenCalledWith(user, "asr", "personal");
  });
});
