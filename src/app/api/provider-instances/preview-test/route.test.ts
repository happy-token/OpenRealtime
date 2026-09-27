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
  return new NextRequest("https://app.test/api/provider-instances/preview-test", {
    method: "POST", headers: { origin, "content-type": "application/json" }, body: JSON.stringify(body),
  });
}

const payload = { capability: "llm", provider: "openai", displayName: "OpenAI", model: "",
  baseUrl: "https://api.openai.com/v1", apiKey: "private-key" };

afterEach(() => vi.clearAllMocks());

it("rejects cross-origin and unsafe base URLs before any vendor call", async () => {
  expect((await POST(request(payload, "https://evil.test"))).status).toBe(403);
  state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
  expect((await POST(request({ ...payload, baseUrl: "http://127.0.0.1:8080" }))).status).toBe(400);
  expect(state.query).not.toHaveBeenCalled();
  expect(state.llm).not.toHaveBeenCalled();
});

it("rate limits a pre-save streaming test without echoing the key", async () => {
  state.actor.mockResolvedValue({ user: { issuer: "issuer", subject: "alice" }, signedIn: true, admin: false });
  state.query.mockResolvedValue({ rowCount: 1 });
  state.llm.mockResolvedValue({ ok: true, message: "流式正常" });
  const response = await POST(request(payload));
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ ok: true, message: "流式正常" });
  expect(state.llm).toHaveBeenCalledWith("openai", "private-key", "", expect.any(Function), "https://api.openai.com/v1");
  state.query.mockResolvedValue({ rowCount: 0 });
  expect((await POST(request(payload))).status).toBe(429);
});
