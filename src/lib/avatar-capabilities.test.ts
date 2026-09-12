import { describe, expect, it } from "vitest";
import { avatarCapabilities } from "./avatar-capabilities";

const request = new Request("http://localhost:3000/api/avatar-capabilities", {
  headers: { referer: "http://localhost:3000/", "sec-fetch-site": "same-origin" },
});

describe("avatar capability preflight", () => {
  it("does not advertise configured paid providers to anonymous users", () => {
    const data = avatarCapabilities(request, false, false, {
      NODE_ENV: "production", ANAM_API_KEY: "secret-provider-key",
      VOICEAGENT_ADMIN_USERNAME: "admin", VOICEAGENT_ADMIN_PASSWORD: "long-password-123",
      VOICEAGENT_ADMIN_SESSION_SECRET: "s".repeat(32),
    });
    expect(data.anam.state).toBe("login_required");
    expect(JSON.stringify(data)).not.toContain("secret-provider-key");
  });
  it("reports missing credentials and disabled local rendering separately", () => {
    const data = avatarCapabilities(request, true, true, { NODE_ENV: "production" });
    expect(data.assets.state).toBe("available");
    expect(data.anam.state).toBe("not_configured");
    expect(data.localRenderer.state).toBe("not_configured");
  });
  it("admits explicitly enabled local preview but does not claim provider health", () => {
    const data = avatarCapabilities(request, true, false, {
      NODE_ENV: "development", ANAM_API_KEY: "key", AVATAR_EVALUATION_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED: "true", AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
      OPENREALTIME_AVATAR_RENDERER_MODE: "external",
    });
    expect(data.anam.state).toBe("available");
    expect(data.localRenderer.state).toBe("available");
    expect(data.anam.message).toContain("启动时");
  });
});
