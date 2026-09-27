import { describe, expect, it } from "vitest";
import { normalizeProviderBaseUrl } from "./provider-catalog";

describe("built-in provider base URLs", () => {
  it("accepts supported official HTTPS endpoints", () => {
    expect(normalizeProviderBaseUrl("asr", "dashscope", "https://llm-workspace.cn-beijing.maas.aliyuncs.com/"))
      .toBe("https://llm-workspace.cn-beijing.maas.aliyuncs.com");
    expect(normalizeProviderBaseUrl("llm", "deepseek", "https://api.deepseek.com/v1/"))
      .toBe("https://api.deepseek.com/v1");
    expect(normalizeProviderBaseUrl("llm", "openai", "https://api.openai.com/v1"))
      .toBe("https://api.openai.com/v1");
  });

  it("rejects redirector, credentials, non-official hosts and unsupported paths", () => {
    expect(normalizeProviderBaseUrl("asr", "dashscope", "https://llm-workspace.cn-beijing.maas.aliyuncs.com.evil.test"))
      .toBeNull();
    for (const url of ["http://api.openai.com/v1", "https://api.openai.com.evil.test/v1",
      "https://user:pass@api.openai.com/v1", "https://api.openai.com:8443/v1",
      "https://api.openai.com/v1/../../admin", "https://api.openai.com/v1?next=http://127.0.0.1"]) {
      expect(normalizeProviderBaseUrl("llm", "openai", url)).toBeNull();
    }
  });
});
