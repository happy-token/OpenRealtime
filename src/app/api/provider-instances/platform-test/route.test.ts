import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ actor: vi.fn(), query: vi.fn(), llm: vi.fn(), speech: vi.fn() }));
vi.mock("@/lib/provider-instance-access", () => ({ providerActor: state.actor }));
vi.mock("@/lib/user-db", () => ({ userDatabase: () => ({ query: state.query }),
  userTable: (name: string) => `voiceagent.${name}` }));
vi.mock("@/lib/provider-credential-test", () => ({ testStreamingLlmInstance: state.llm }));
vi.mock("@/lib/provider-contract-test", () => ({ testProviderContract: state.speech }));

import { POST } from "./route";

function request(body: object, origin = "https://app.test") {
  return new NextRequest("https://app.test/api/provider-instances/platform-test", {
    method: "POST", headers: { origin, "content-type": "application/json" }, body: JSON.stringify(body),
  });
}

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); });

it("requires authentication and tests only supported configured platform providers", async () => {
  const input = { capability: "llm", provider: "deepseek" };
  expect((await POST(request(input, "https://evil.test"))).status).toBe(403);
  expect((await POST(request(input))).status).toBe(401);
  state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
  expect((await POST(request(input))).status).toBe(404);
  expect((await POST(request({ capability: "asr", provider: "openai" }))).status).toBe(400);
  expect(state.llm).not.toHaveBeenCalled();
});

it("uses the platform key without returning it and applies a shared cooldown", async () => {
  vi.stubEnv("DEEPSEEK_API_KEY", "platform-secret-7890");
  state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
  state.query.mockResolvedValue({ rowCount: 1 });
  state.llm.mockResolvedValue({ ok: true, message: "流式正常" });
  const input = { capability: "llm", provider: "deepseek" };
  const response = await POST(request(input));
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ ok: true, message: "流式正常" });
  expect(state.llm).toHaveBeenCalledWith("deepseek", "platform-secret-7890", "");
  expect(state.query).toHaveBeenCalledWith(expect.stringContaining("provider_preview_test_limits"), ["llm:deepseek"]);
  state.query.mockResolvedValue({ rowCount: 0 });
  expect((await POST(request(input))).status).toBe(429);
});
