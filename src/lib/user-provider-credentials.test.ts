import { afterEach, describe, expect, it, vi } from "vitest";
import {
  parsePersonalKeyProvider,
  sealPersonalKey,
  unsealPersonalKey,
} from "./user-provider-credentials";

afterEach(() => vi.unstubAllEnvs());

describe("personal provider credential encryption", () => {
  it("decrypts only for the same account and provider", () => {
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 7).toString("base64url"));
    const owner = { issuer: "https://login.example", subject: "user-a" };
    const sealed = sealPersonalKey(owner, "anam", "private-provider-key");
    expect(sealed.toString()).not.toContain("private-provider-key");
    expect(unsealPersonalKey(owner, "anam", sealed)).toBe("private-provider-key");
    expect(() => unsealPersonalKey({ ...owner, subject: "user-b" }, "anam", sealed)).toThrow();
    expect(() => unsealPersonalKey(owner, "minimax", sealed)).toThrow();
    sealed[20] ^= 1;
    expect(() => unsealPersonalKey(owner, "anam", sealed)).toThrow();
  });

  it("rejects unsupported providers and missing encryption configuration", () => {
    expect(parsePersonalKeyProvider("other")).toBeNull();
    expect(parsePersonalKeyProvider("doubao")).toBe("doubao");
    expect(parsePersonalKeyProvider("openai")).toBe("openai");
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", "");
    expect(() => sealPersonalKey({ issuer: "i", subject: "s" }, "anam", "key"))
      .toThrow("用户 API Key 加密密钥尚未配置");
  });
});
