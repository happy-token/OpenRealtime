import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({
  user: vi.fn(), lip: vi.fn(), list: vi.fn(), load: vi.fn(), save: vi.fn(), delete: vi.fn(),
  saveLip: vi.fn(), deleteLip: vi.fn(), probe: vi.fn(),
}));
vi.mock("@/lib/user-session", () => ({ userFromRequest: dependencies.user }));
vi.mock("@/lib/user-lipsync-service", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/user-lipsync-service")>(),
  loadUserLipsyncService: dependencies.lip, saveUserLipsyncService: dependencies.saveLip, deleteUserLipsyncService: dependencies.deleteLip,
}));
vi.mock("@/lib/user-talking-model-services", () => ({
  isPersonalTalkingKind: (value: unknown) => value === "musetalk" || value === "wav2lip",
  listUserTalkingServices: dependencies.list, loadUserTalkingService: dependencies.load,
  saveUserTalkingService: dependencies.save, deleteUserTalkingService: dependencies.delete,
}));
vi.mock("@/lib/model-service-connections", () => ({ probeModelService: dependencies.probe }));

import { GET, PATCH } from "./route";
import { POST as TEST_CONNECTION } from "./test/route";

const alice = { issuer: "https://issuer.example", subject: "alice" };
const bob = { issuer: "https://issuer.example", subject: "bob" };
const url = "https://models.example";

function request(method: "GET" | "PATCH" | "POST", body?: object, origin = "http://localhost:3010") {
  return new NextRequest("http://localhost:3010/api/user/model-services", {
    method, headers: { origin, ...(body ? { "content-type": "application/json" } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

describe("personal model services API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", url);
    dependencies.user.mockResolvedValue(alice);
    dependencies.lip.mockResolvedValue(null);
    dependencies.list.mockResolvedValue({ musetalk: null, wav2lip: null });
    dependencies.load.mockResolvedValue(null);
    dependencies.save.mockImplementation(async (_user, _kind, savedUrl, token) => ({ url: savedUrl, token: token ?? "" }));
    dependencies.probe.mockResolvedValue({ ready: true, message: "连接正常" });
  });
  afterEach(() => vi.unstubAllEnvs());

  it("requires a signed-in user and a same-origin mutation", async () => {
    dependencies.user.mockResolvedValueOnce(null);
    expect((await GET(request("GET"))).status).toBe(401);
    expect((await PATCH(request("PATCH", { kind: "musetalk", url }, "http://evil.example"))).status).toBe(403);
  });

  it("keeps each user's model service separate and never returns its token", async () => {
    const saved = await PATCH(request("PATCH", { kind: "musetalk", url, token: "alice-secret" }));
    expect(saved.status).toBe(200);
    expect(dependencies.save).toHaveBeenCalledWith(alice, "musetalk", url, "alice-secret");
    expect(JSON.stringify(await saved.json())).not.toContain("alice-secret");
    dependencies.user.mockResolvedValue(bob);
    await PATCH(request("PATCH", { kind: "wav2lip", url }));
    expect(dependencies.save).toHaveBeenCalledWith(bob, "wav2lip", url, undefined);
    const listed = await GET(request("GET"));
    expect((await listed.json()).services).toMatchObject({ musetalk: { url: "", tokenConfigured: false } });
  });

  it("rejects unapproved or private service targets", async () => {
    for (const target of ["http://127.0.0.1:18191", "https://other.example", "file:///etc/passwd"]) {
      expect((await PATCH(request("PATCH", { kind: "musetalk", url: target }))).status).toBe(400);
    }
    expect(dependencies.save).not.toHaveBeenCalled();
  });

  it("does not send a stored token when testing a different URL", async () => {
    dependencies.load.mockResolvedValue({ url, token: "stored-secret" });
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", `${url},https://other.example`);
    const response = await TEST_CONNECTION(request("POST", { kind: "musetalk", url: "https://other.example" }));
    expect(response.status).toBe(200);
    expect(dependencies.probe).toHaveBeenCalledWith("musetalk", { url: "https://other.example", token: "" });
  });
});
