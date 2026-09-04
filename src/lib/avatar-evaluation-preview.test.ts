import { describe, expect, it } from "vitest";
import {
  avatarEvaluationPreviewPolicyFromEnv,
  isSameOriginAvatarPreviewRequest,
} from "./avatar-evaluation-preview";

describe("avatarEvaluationPreviewPolicyFromEnv", () => {
  it("allows an explicit local-development preview without weakening production", () => {
    expect(avatarEvaluationPreviewPolicyFromEnv({
      NODE_ENV: "development",
      AVATAR_EVALUATION_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toEqual({ enabled: true, localDevelopmentAccess: true });

    expect(avatarEvaluationPreviewPolicyFromEnv({
      NODE_ENV: "production",
      AVATAR_EVALUATION_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOOPBACK_BOUND: "true",
    })).toEqual({ enabled: true, localDevelopmentAccess: false });
  });

  it("rejects a direct Next dev process that is not launched loopback-only", () => {
    expect(avatarEvaluationPreviewPolicyFromEnv({
      NODE_ENV: "development",
      AVATAR_EVALUATION_PREVIEW_ENABLED: "true",
      AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED: "true",
    })).toEqual({ enabled: true, localDevelopmentAccess: false });
  });

  it("keeps all preview access disabled unless the main switch is explicit", () => {
    expect(avatarEvaluationPreviewPolicyFromEnv({
      NODE_ENV: "development",
      AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED: "true",
    })).toEqual({ enabled: false, localDevelopmentAccess: false });
  });
});

describe("isSameOriginAvatarPreviewRequest", () => {
  it("accepts only a same-origin browser media request", () => {
    expect(isSameOriginAvatarPreviewRequest(new Request(
      "http://localhost:3010/api/avatar-evaluation/artifacts/static-base",
      { headers: {
        referer: "http://localhost:3010/",
        "sec-fetch-site": "same-origin",
      } },
    ))).toBe(true);

    expect(isSameOriginAvatarPreviewRequest(new Request(
      "http://localhost:3010/api/avatar-evaluation/artifacts/static-base",
      { headers: {
        referer: "http://127.0.0.1:3010/",
        "sec-fetch-site": "same-origin",
      } },
    ))).toBe(true);
  });

  it("rejects cross-site, missing-referrer, and mismatched-port requests", () => {
    const url = "http://localhost:3010/api/avatar-evaluation/artifacts/static-base";
    expect(isSameOriginAvatarPreviewRequest(new Request(url, { headers: {
      referer: "https://malicious.example/",
      "sec-fetch-site": "cross-site",
    } }))).toBe(false);
    expect(isSameOriginAvatarPreviewRequest(new Request(url, { headers: {
      "sec-fetch-site": "same-origin",
    } }))).toBe(false);
    expect(isSameOriginAvatarPreviewRequest(new Request(url, { headers: {
      referer: "http://127.0.0.1:3011/",
      "sec-fetch-site": "same-origin",
    } }))).toBe(false);
    expect(isSameOriginAvatarPreviewRequest(new Request(
      "http://192.168.1.9:3010/api/avatar-evaluation/artifacts/static-base",
      { headers: {
        referer: "http://192.168.1.9:3010/",
        "sec-fetch-site": "same-origin",
      } },
    ))).toBe(false);
  });
});
