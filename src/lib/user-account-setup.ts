const REQUIRED_ACCOUNT_SETTINGS = [
  "VOICEAGENT_CASDOOR_ISSUER",
  "VOICEAGENT_CASDOOR_CLIENT_ID",
  "VOICEAGENT_CASDOOR_CLIENT_SECRET",
  "VOICEAGENT_PUBLIC_ORIGIN",
  "VOICEAGENT_USER_SESSION_SECRET",
  "VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY",
  "VOICEAGENT_POSTGRES_DSN",
] as const;

export function missingUserAccountSettings(env: Record<string, string | undefined> = process.env): string[] {
  const missing = REQUIRED_ACCOUNT_SETTINGS.filter((name) => !env[name]?.trim());
  if (env.VOICEAGENT_USER_SESSION_SECRET?.trim()
    && env.VOICEAGENT_USER_SESSION_SECRET.length < 32) {
    missing.push("VOICEAGENT_USER_SESSION_SECRET");
  }
  return [...new Set(missing)];
}
