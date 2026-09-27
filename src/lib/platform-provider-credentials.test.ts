import { afterEach, expect, it, vi } from "vitest";
import { listPlatformProviderCredentials } from "./platform-provider-credentials";

afterEach(() => vi.unstubAllEnvs());

it("shows the configured DashScope key for ASR and fills the workspace URL", () => {
  vi.stubEnv("DASHSCOPE_API_KEY", "private-key-1234");
  vi.stubEnv("DASHSCOPE_WORKSPACE_ID", "llm-workspace");
  const rows = listPlatformProviderCredentials().filter((row) => row.provider === "dashscope");
  expect(rows.map((row) => row.capability)).toEqual(["asr", "tts"]);
  expect(rows[0]).toMatchObject({ keySuffix: "1234",
    baseUrl: "https://llm-workspace.cn-beijing.maas.aliyuncs.com" });
  expect(JSON.stringify(rows)).not.toContain("private-key");
});
