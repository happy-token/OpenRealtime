import { describe, expect, it } from "vitest";
import {
  ADMIN_SESSION_COOKIE,
  createAdminSessionToken,
} from "./admin-auth";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "./avatar-test-access";

const admin = {
  username: "operator",
  password: "correct-horse-battery-staple",
  sessionSecret: "a-session-signing-secret-with-enough-entropy",
};

function localRequest(url = "http://127.0.0.1:3010/api/vidu/account") {
  return new Request(url, {
    headers: {
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

describe("avatar test API access", () => {
  it("allows an authenticated administrator", () => {
    const token = createAdminSessionToken(admin);
    expect(canUseAvatarTestApis(
      new Request("https://app.example.com/api/vidu/account"),
      token,
      {
        VOICEAGENT_ADMIN_USERNAME: admin.username,
        VOICEAGENT_ADMIN_PASSWORD: admin.password,
        VOICEAGENT_ADMIN_SESSION_SECRET: admin.sessionSecret,
        NODE_ENV: "production",
      },
    )).toBe(true);
    expect(ADMIN_SESSION_COOKIE).toBe("voiceagent_admin_session");
  });

  it("allows explicit same-origin loopback access in development", () => {
    expect(canUseAvatarTestApis(localRequest(), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(true);
  });

  it("allows same-origin loopback browsers that omit Sec-Fetch-Site", () => {
    expect(canUseAvatarTestApis(new Request("http://127.0.0.1:3010/api/vidu/account", {
      headers: { referer: "http://127.0.0.1:3010/avatar-video" },
    }), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(true);
  });

  it("rejects an explicit cross-site browser request even with a same-origin referer", () => {
    expect(canUseAvatarTestApis(new Request("http://127.0.0.1:3010/api/vidu/account", {
      headers: {
        referer: "http://127.0.0.1:3010/avatar-video",
        "sec-fetch-site": "cross-site",
      },
    }), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(false);
  });

  it("rejects forged headers, cross-origin requests, and production test mode", () => {
    expect(canUseAvatarTestApis(new Request("http://127.0.0.1:3010/api/vidu/account", {
      headers: { "x-openrealtime-client": "digital-human-video-ui" },
    }), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(false);
    expect(canUseAvatarTestApis(localRequest("http://127.0.0.1:3011/api/vidu/account"), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(false);
    expect(canUseAvatarTestApis(localRequest(), undefined, {
      NODE_ENV: "production",
      AVATAR_LOCAL_TEST_MODE: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toBe(false);
  });

  it("rejects local mode when the process was not started by the loopback launcher", () => {
    expect(canUseAvatarTestApis(localRequest(), undefined, {
      NODE_ENV: "development",
      AVATAR_LOCAL_TEST_MODE: "true",
    })).toBe(false);
  });

  it("requires state-changing requests to come from the exact application origin", () => {
    expect(isSameOriginAvatarMutation(localRequest())).toBe(true);
    expect(isSameOriginAvatarMutation(new Request("http://localhost:3010/api/vidu/image-to-video", {
      headers: {
        host: "127.0.0.1:3010",
        origin: "http://127.0.0.1:3010",
      },
    }))).toBe(true);
    expect(isSameOriginAvatarMutation(new Request("https://app.example.com/api/vidu/image-to-video", {
      headers: { origin: "https://evil.example.com" },
    }))).toBe(false);
    expect(isSameOriginAvatarMutation(new Request("https://app.example.com/api/vidu/image-to-video"))).toBe(false);
  });
});
