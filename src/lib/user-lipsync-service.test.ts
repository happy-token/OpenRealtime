import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { normalizePersonalLipsyncUrl, sealLipsyncToken, unsealLipsyncToken, probeUserLipsyncService } from "./user-lipsync-service";

const user = { issuer: "https://identity.example", subject: "alice" };
const other = { ...user, subject: "bob" };

describe("personal lip-sync service boundary", () => {
  beforeEach(() => {
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", "https://models.example");
    vi.stubEnv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", Buffer.alloc(32, 7).toString("base64url"));
  });
  afterEach(() => vi.unstubAllEnvs());

  it("only accepts an exact operator-approved HTTPS origin", () => {
    expect(normalizePersonalLipsyncUrl("https://models.example")).toBe("https://models.example");
    for (const url of ["http://models.example", "https://models.example.evil.test", "https://models.example/path", "https://127.0.0.1", "https://models.example?x=1"]) {
      expect(() => normalizePersonalLipsyncUrl(url)).toThrow();
    }
  });

  it("accepts an approved public IP and port without credentials or paths", () => {
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", "http://101.96.195.224:8190");
    expect(normalizePersonalLipsyncUrl("http://101.96.195.224:8190")).toBe("http://101.96.195.224:8190");
    for (const url of ["http://101.96.195.224:8191", "http://101.96.195.225:8190", "http://101.96.195.224:8190/path", "http://user:pass@101.96.195.224:8190", "http://101.96.195.224:8190?x=1"]) {
      expect(() => normalizePersonalLipsyncUrl(url)).toThrow();
    }
  });

  it("encrypts tokens for one account only", () => {
    const sealed = sealLipsyncToken(user, "private-token");
    expect(sealed.toString()).not.toContain("private-token");
    expect(unsealLipsyncToken(user, sealed)).toBe("private-token");
    expect(() => unsealLipsyncToken(other, sealed)).toThrow();
  });

  it("accepts only explicitly approved local HTTP tunnels", () => {
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", "http://127.0.0.1:18190");
    expect(normalizePersonalLipsyncUrl("http://127.0.0.1:18190/")).toBe("http://127.0.0.1:18190");
    for (const url of ["http://127.0.0.1:18191", "http://localhost:18190", "http://127.0.0.1:18190/path", "http://user:pass@127.0.0.1:18190", "http://127.0.0.1:18190?x=1"]) {
      expect(() => normalizePersonalLipsyncUrl(url)).toThrow();
    }
    vi.stubEnv("VOICEAGENT_PERSONAL_LIPSYNC_ALLOWED_ORIGINS", "http://models.example");
    expect(normalizePersonalLipsyncUrl("http://models.example")).toBe("http://models.example");
  });

  it("checks model identity without following redirects", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ status: "ok", model: "lipforcing-14b" }));
    expect(await probeUserLipsyncService({ url: "https://models.example", token: "secret" })).toBe(true);
    expect(fetcher).toHaveBeenCalledWith("https://models.example/health", expect.objectContaining({ redirect: "manual", headers: { Authorization: "Bearer secret" } }));
    fetcher.mockRestore();
  });
});
