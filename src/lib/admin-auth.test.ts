import { describe, expect, it } from "vitest";
import {
  adminLoginDefaultsFromEnv,
  createAdminSessionToken,
  verifyAdminCredentials,
  verifyAdminSessionToken,
} from "./admin-auth";

const config = {
  username: "operator",
  password: "correct-horse-battery-staple",
  sessionSecret: "a-session-signing-secret-with-enough-entropy",
};

describe("admin authentication", () => {
  it("accepts only the configured credentials", () => {
    expect(verifyAdminCredentials("operator", "correct-horse-battery-staple", config)).toBe(true);
    expect(verifyAdminCredentials("operator", "wrong", config)).toBe(false);
    expect(verifyAdminCredentials("someone-else", "correct-horse-battery-staple", config)).toBe(false);
  });

  it("rejects modified and expired session tokens", () => {
    const token = createAdminSessionToken(config, { nowMs: 1_000, maxAgeSeconds: 60 });
    expect(verifyAdminSessionToken(token, config, { nowMs: 30_000 })).toEqual({ username: "operator" });
    expect(verifyAdminSessionToken(`${token}x`, config, { nowMs: 30_000 })).toBeNull();
    expect(verifyAdminSessionToken(token, config, { nowMs: 62_000 })).toBeNull();
  });

  it("prefills credentials only when a non-production environment explicitly enables it", () => {
    const env = {
      VOICEAGENT_ADMIN_USERNAME: config.username,
      VOICEAGENT_ADMIN_PASSWORD: config.password,
      VOICEAGENT_ADMIN_SESSION_SECRET: config.sessionSecret,
      VOICEAGENT_ADMIN_AUTOFILL: "true",
      VOICEAGENT_ENV: "test",
      NODE_ENV: "test",
    } satisfies NodeJS.ProcessEnv;
    expect(adminLoginDefaultsFromEnv(env)).toEqual({
      username: config.username,
      password: config.password,
    });
    expect(adminLoginDefaultsFromEnv({ ...env, VOICEAGENT_ADMIN_AUTOFILL: "false" })).toBeNull();
  });

  it("never prefills credentials in production", () => {
    expect(adminLoginDefaultsFromEnv({
      VOICEAGENT_ADMIN_USERNAME: config.username,
      VOICEAGENT_ADMIN_PASSWORD: config.password,
      VOICEAGENT_ADMIN_SESSION_SECRET: config.sessionSecret,
      VOICEAGENT_ADMIN_AUTOFILL: "true",
      VOICEAGENT_ENV: "test",
      NODE_ENV: "production",
    })).toBeNull();
  });
});
