import { afterEach, describe, expect, it, vi } from "vitest";
import { assertSafeLtxResultUrl } from "./ltx-result-url";

afterEach(() => vi.unstubAllEnvs());

describe("LTX result URL policy", () => {
  it("accepts a public HTTPS result and honors an optional host allowlist", async () => {
    vi.stubEnv("LTX_RESULT_HOST_ALLOWLIST", "media.ltx.test");
    await expect(assertSafeLtxResultUrl(
      "https://media.ltx.test/result.mp4",
      async () => [{ address: "93.184.216.34", family: 4 }],
    )).resolves.toBe("https://media.ltx.test/result.mp4");
  });

  it.each(["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fd00::1"])(
    "rejects non-public DNS answer %s",
    async (address) => {
      await expect(assertSafeLtxResultUrl(
        "https://media.ltx.test/result.mp4",
        async () => [{ address, family: address.includes(":") ? 6 : 4 }],
      )).rejects.toThrow("非公网地址");
    },
  );

  it("rejects credentials, plain HTTP, and hosts outside a configured allowlist", async () => {
    vi.stubEnv("LTX_RESULT_HOST_ALLOWLIST", "media.ltx.test");
    await expect(assertSafeLtxResultUrl("https://evil.test/result.mp4")).rejects.toThrow("允许列表");
    await expect(assertSafeLtxResultUrl("http://media.ltx.test/result.mp4")).rejects.toThrow("不受信任");
  });

  it("verifies proxy Fake-IP answers against public DNS without allowing real private targets", async () => {
    await expect(assertSafeLtxResultUrl(
      "https://media.ltx.test/result.mp4",
      async () => [{ address: "198.18.0.124", family: 4 }],
      async () => [{ address: "47.102.9.67", family: 4 }],
    )).resolves.toBe("https://media.ltx.test/result.mp4");

    await expect(assertSafeLtxResultUrl(
      "https://media.ltx.test/result.mp4",
      async () => [{ address: "192.168.1.20", family: 4 }],
      async () => [{ address: "47.102.9.67", family: 4 }],
    )).rejects.toThrow("非公网地址");
  });
});
