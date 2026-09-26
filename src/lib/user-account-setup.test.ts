import { describe, expect, it } from "vitest";
import { missingUserAccountSettings } from "./user-account-setup";

describe("user account setup", () => {
  it("identifies missing settings without exposing their values", () => {
    expect(missingUserAccountSettings({
      VOICEAGENT_CASDOOR_ISSUER: "https://login.example",
      VOICEAGENT_USER_SESSION_SECRET: "too-short",
    })).toEqual([
      "VOICEAGENT_CASDOOR_CLIENT_ID",
      "VOICEAGENT_CASDOOR_CLIENT_SECRET",
      "VOICEAGENT_PUBLIC_ORIGIN",
      "VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY",
      "VOICEAGENT_POSTGRES_DSN",
      "VOICEAGENT_USER_SESSION_SECRET",
    ]);
  });
});
