import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

afterEach(() => vi.unstubAllEnvs());

describe("ordinary user login", () => {
  it("returns to supplier settings when account login is not configured", async () => {
    for (const name of [
      "VOICEAGENT_CASDOOR_ISSUER", "VOICEAGENT_CASDOOR_CLIENT_ID",
      "VOICEAGENT_CASDOOR_CLIENT_SECRET", "VOICEAGENT_PUBLIC_ORIGIN",
      "VOICEAGENT_USER_SESSION_SECRET", "VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY",
      "VOICEAGENT_POSTGRES_DSN",
    ]) vi.stubEnv(name, "");
    const response = await GET(new NextRequest("http://localhost:3000/api/user/login?next=/settings/providers"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/settings/providers");
  });

  it("moves local aliases to the configured origin before creating the OIDC flow cookie", async () => {
    for (const [name, value] of Object.entries({
      VOICEAGENT_CASDOOR_ISSUER: "https://login.example",
      VOICEAGENT_CASDOOR_CLIENT_ID: "client",
      VOICEAGENT_CASDOOR_CLIENT_SECRET: "secret",
      VOICEAGENT_PUBLIC_ORIGIN: "http://127.0.0.1:3010",
      VOICEAGENT_USER_SESSION_SECRET: "a".repeat(32),
      VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY: "b".repeat(43),
      VOICEAGENT_POSTGRES_DSN: "postgresql://localhost/test",
    })) vi.stubEnv(name, value);

    const response = await GET(new NextRequest("http://localhost:3010/api/user/login?next=/settings/providers"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://127.0.0.1:3010/api/user/login?next=%2Fsettings%2Fproviders");
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
