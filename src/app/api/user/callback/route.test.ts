import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/user-oidc", () => ({
  OIDC_FLOW_COOKIE: "openrealtime_oidc_flow",
  finishOidcLogin: vi.fn(async () => ({
    issuer: "https://login.example", subject: "test-user", returnTo: "/settings/providers",
  })),
}));
vi.mock("@/lib/user-session", () => ({
  USER_SESSION_COOKIE: "openrealtime_user_session",
  USER_SESSION_SECONDS: 28800,
  createUserSession: vi.fn(async () => "fake-session-token"),
}));

import { finishOidcLogin } from "@/lib/user-oidc";
import { GET } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("Casdoor callback origin", () => {
  it("uses the configured public origin when Next normalizes its internal URL", async () => {
    vi.stubEnv("VOICEAGENT_PUBLIC_ORIGIN", "http://127.0.0.1:3010");
    const request = new NextRequest("http://localhost:3010/api/user/callback?code=fake&state=state", {
      headers: { host: "127.0.0.1:3010", cookie: "openrealtime_oidc_flow=flow" },
    });

    const response = await GET(request);

    expect(response.status).toBe(307);
    expect(vi.mocked(finishOidcLogin).mock.calls[0]?.[0].origin).toBe("http://127.0.0.1:3010");
    expect(response.headers.get("location")).toBe("http://127.0.0.1:3010/settings/providers");
    expect(response.headers.get("set-cookie")).toContain("openrealtime_user_session=fake-session-token");
  });

  it("rejects a callback delivered for another host", async () => {
    vi.stubEnv("VOICEAGENT_PUBLIC_ORIGIN", "http://127.0.0.1:3010");
    const response = await GET(new NextRequest("http://localhost:3010/api/user/callback?code=fake", {
      headers: { host: "other.example", cookie: "openrealtime_oidc_flow=flow" },
    }));

    expect(vi.mocked(finishOidcLogin)).not.toHaveBeenCalled();
    expect(response.headers.get("location")).toBe("http://127.0.0.1:3010/settings/providers?loginError=provider");
  });
});
