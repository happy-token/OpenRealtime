import { afterEach, describe, expect, it, vi } from "vitest";
import { assertSafeViduResultUrl } from "./vidu-result-url";

afterEach(() => vi.unstubAllEnvs());

describe("Vidu result URL policy", () => {
  it("accepts an allowlisted HTTPS host only when every DNS answer is public", async () => {
    vi.stubEnv("VIDU_RESULT_HOST_ALLOWLIST", "media.vidu.test");
    const resolver = vi.fn(async () => [{ address: "93.184.216.34", family: 4 }]);
    await expect(assertSafeViduResultUrl("https://media.vidu.test/result.mp4", resolver))
      .resolves.toBe("https://media.vidu.test/result.mp4");
    expect(resolver).toHaveBeenCalledWith("media.vidu.test");
  });

  it.each(["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fd00::1"])(
    "rejects non-public DNS answer %s",
    async (address) => {
      vi.stubEnv("VIDU_RESULT_HOST_ALLOWLIST", "media.vidu.test");
      await expect(assertSafeViduResultUrl(
        "https://media.vidu.test/result.mp4",
        async () => [{ address, family: address.includes(":") ? 6 : 4 }],
      )).rejects.toThrow("非公网地址");
    },
  );

  it("rejects arbitrary hosts and non-HTTPS URLs before downloading", async () => {
    vi.stubEnv("VIDU_RESULT_HOST_ALLOWLIST", "media.vidu.test");
    await expect(assertSafeViduResultUrl("https://evil.example/result.mp4")).rejects.toThrow("允许列表");
    await expect(assertSafeViduResultUrl("http://media.vidu.test/result.mp4")).rejects.toThrow("不受信任");
  });
});
