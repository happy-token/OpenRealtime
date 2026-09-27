import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ actor: vi.fn(), update: vi.fn(), remove: vi.fn(), select: vi.fn(),
  load: vi.fn(), claim: vi.fn(), record: vi.fn(), testCredential: vi.fn(), testStreaming: vi.fn(), testContract: vi.fn() }));
vi.mock("@/lib/provider-instance-access", () => ({ providerActor: state.actor,
  validInstanceId: (value: string) => /^[0-9a-f-]{36}$/i.test(value) }));
vi.mock("@/lib/provider-instances", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/provider-instances")>();
  return { ...original, updateProviderInstance: state.update, deleteProviderInstance: state.remove,
    selectProviderInstance: state.select, loadProviderInstanceKey: state.load,
    claimProviderConnectionTest: state.claim, recordProviderConnectionTest: state.record };
});
vi.mock("@/lib/provider-credential-test", () => ({ isTestableProvider: () => true,
  testProviderCredential: state.testCredential, testStreamingLlmInstance: state.testStreaming }));
vi.mock("@/lib/provider-contract-test", () => ({ testProviderContract: state.testContract }));

import { PATCH, DELETE } from "./route";
import { POST as SELECT } from "./select/route";
import { POST as TEST } from "./test/route";

const id = "d7952389-59d1-4a4d-9d89-9642d851544b";
const params = { params: Promise.resolve({ instanceId: id }) };
const user = { issuer: "issuer", subject: "alice" };

function request(method: "PATCH" | "DELETE" | "POST", path = "", body?: object) {
  return new NextRequest(`https://app.test/api/provider-instances/${id}${path}`, {
    method, headers: { origin: "https://app.test", "content-type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

afterEach(() => vi.clearAllMocks());

it("rejects ordinary user writes to platform instances", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  const input = { scope: "platform", capability: "llm", provider: "openai", displayName: "平台",
    model: "", expectedRevision: id };
  expect((await PATCH(request("PATCH", "", input), params)).status).toBe(403);
  expect((await DELETE(request("DELETE", "?scope=platform"), params)).status).toBe(403);
  expect((await SELECT(request("POST", "/select?scope=platform"), params)).status).toBe(403);
  expect(state.update).not.toHaveBeenCalled();
  expect(state.remove).not.toHaveBeenCalled();
  expect(state.select).not.toHaveBeenCalled();
});

it("returns a conflict instead of deleting a selected instance", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  state.remove.mockRejectedValue(new Error("请先切换正在使用的实例，再删除此配置"));
  const response = await DELETE(request("DELETE"), params);
  expect(response.status).toBe(409);
  expect(state.remove).toHaveBeenCalledWith(user, "personal", id);
});

it("enforces an atomic cooldown before a potentially billable connection test", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  state.load.mockResolvedValue({ instance: { scope: "personal", capability: "tts", provider: "doubao" },
    key: "private-key", keyVersion: id });
  state.claim.mockResolvedValue(false);
  const response = await TEST(request("POST", "/test"), params);
  expect(response.status).toBe(429);
  expect(response.headers.get("Retry-After")).toBe("60");
  expect(state.testCredential).not.toHaveBeenCalled();
});

it("tests selected LLM model with real streaming semantics rather than a model list", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  state.load.mockResolvedValue({ instance: { scope: "personal", capability: "llm", provider: "openai", model: "gpt-selected", baseUrl: "https://api.openai.com/v1" },
    key: "private-key", keyVersion: id });
  state.claim.mockResolvedValue(true);
  state.testStreaming.mockResolvedValue({ ok: true, message: "流式文本正常", firstTextMs: 12 });
  state.record.mockResolvedValue(true);
  const response = await TEST(request("POST", "/test"), params);
  expect(response.status).toBe(200);
  expect(await response.json()).toMatchObject({ ok: true, level: "streaming", firstTextMs: 12 });
  expect(state.testStreaming).toHaveBeenCalledWith("openai", "private-key", "gpt-selected", expect.any(Function), "https://api.openai.com/v1");
  expect(state.testCredential).not.toHaveBeenCalled();
});

it("tests a selected ASR instance with its own key and records only the contract result", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  state.load.mockResolvedValue({ instance: { scope: "personal", capability: "asr", provider: "doubao", model: "" },
    key: "asr-instance-key", keyVersion: id });
  state.claim.mockResolvedValue(true);
  state.testContract.mockResolvedValue({ ok: true, message: "partial/final 已验证", level: "contract" });
  state.record.mockResolvedValue(true);
  const response = await TEST(request("POST", "/test"), params);
  expect(response.status).toBe(200);
  expect(await response.json()).toMatchObject({ ok: true, level: "contract" });
  expect(state.testContract).toHaveBeenCalledWith("asr", "doubao", "asr-instance-key");
  expect(state.testCredential).not.toHaveBeenCalled();
});

it("tests TTS duplex behavior rather than just its model or connection", async () => {
  state.actor.mockResolvedValue({ user, signedIn: true, admin: false });
  state.load.mockResolvedValue({ instance: { scope: "personal", capability: "tts", provider: "dashscope", model: "" },
    key: "tts-instance-key", keyVersion: id });
  state.claim.mockResolvedValue(true);
  state.testContract.mockResolvedValue({ ok: true, message: "双流式已验证", firstOutputMs: 125.4 });
  state.record.mockResolvedValue(true);
  const response = await TEST(request("POST", "/test"), params);
  expect(response.status).toBe(200);
  expect(await response.json()).toMatchObject({ ok: true, level: "contract", message: "双流式已验证；首音 125 ms" });
  expect(state.testContract).toHaveBeenCalledWith("tts", "dashscope", "tts-instance-key");
  expect(state.testCredential).not.toHaveBeenCalled();
  expect(state.record).toHaveBeenCalledWith(user, "personal", id, id, true, "双流式已验证；首音 125 ms");
});
