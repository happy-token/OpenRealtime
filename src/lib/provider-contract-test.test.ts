import { EventEmitter } from "node:events";
import { createHmac } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn: state.spawn }));

import { ProviderContractUnavailableError, testProviderContract } from "./provider-contract-test";

afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("does not start ASR testing without an authorized audio fixture key", async () => {
  vi.stubEnv("DOUBAO_API_KEY", "");
  await expect(testProviderContract("asr", "doubao", "private-asr-key"))
    .rejects.toBeInstanceOf(ProviderContractUnavailableError);
  expect(state.spawn).not.toHaveBeenCalled();
});

it("passes only fixed probe arguments, sends credentials on stdin, and returns a bounded summary", async () => {
  vi.stubEnv("DOUBAO_API_KEY", "platform-fixture-key");
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter & { setEncoding: (encoding: string) => void };
    stdin: EventEmitter & { end: (payload: string) => void };
    kill: (signal: string) => void;
  };
  let input = "";
  child.stdout = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  child.stdin = Object.assign(new EventEmitter(), { end: (payload: string) => { input = payload; } });
  child.kill = vi.fn();
  state.spawn.mockReturnValue(child);

  const pending = testProviderContract("asr", "doubao", "private-asr-key");
  child.stdout.emit("data", '{"ok":true,"message":"partial/final 文本已验证","firstOutputMs":123}');
  child.emit("close", 0);

  await expect(pending).resolves.toMatchObject({ ok: true, firstOutputMs: 123 });
  const [executable, args, options] = state.spawn.mock.calls[0];
  expect(executable).not.toContain("private-asr-key");
  expect(args).toEqual(["-m", "server.speech.provider_contract_probe"]);
  expect(JSON.parse(input)).toEqual({ capability: "asr", provider: "doubao",
    apiKey: "private-asr-key", fixtureTtsKey: "platform-fixture-key" });
  expect(JSON.stringify(options.env)).not.toContain("private-asr-key");
  expect(JSON.stringify(options.env)).not.toContain("platform-fixture-key");
});

it("signs the instance-key probe to the loopback voice service without forwarding the platform fixture key", async () => {
  const key = Buffer.alloc(32, 7);
  vi.stubEnv("VOICEAGENT_CONTROL_PLANE_URL", "http://127.0.0.1:8766");
  vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", key.toString("base64url"));
  vi.stubEnv("DOUBAO_API_KEY", "platform-fixture-key");
  const fetchMock = vi.fn(async (_url: URL, init: RequestInit) => {
    const headers = init.headers as Record<string, string>;
    const body = init.body as string;
    const expected = createHmac("sha256", key)
      .update(`provider-contract-probe-v1\0${headers["X-Provider-Probe-Timestamp"]}\0${body}`).digest("hex");
    expect(headers["X-Provider-Probe-Signature"]).toBe(expected);
    expect(JSON.parse(body)).toEqual({ capability: "asr", provider: "doubao", apiKey: "private-asr-key" });
    return new Response(JSON.stringify({ ok: true, message: "partial/final 文本已验证" }));
  });
  vi.stubGlobal("fetch", fetchMock);

  await expect(testProviderContract("asr", "doubao", "private-asr-key"))
    .resolves.toMatchObject({ ok: true });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(state.spawn).not.toHaveBeenCalled();
});

it("rejects a non-loopback voice-service URL before transmitting credentials", async () => {
  vi.stubEnv("VOICEAGENT_CONTROL_PLANE_URL", "https://attacker.example");
  await expect(testProviderContract("tts", "doubao", "private-tts-key"))
    .rejects.toBeInstanceOf(ProviderContractUnavailableError);
  expect(state.spawn).not.toHaveBeenCalled();
});
