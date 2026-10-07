import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { issueDiagnosticsAccess, verifyDiagnosticsAccess } from "./diagnostics-access";

const secret = "test-only-diagnostics-secret-32-characters";
const now = 1_800_000_000_000;
describe("Session-scoped diagnostic credentials", () => {
  it("has a distinct read-only identity, scope and absolute 15 minute expiry", () => {
    const grant = issueDiagnosticsAccess("session-1", "debug-agent", secret, now);
    expect(verifyDiagnosticsAccess(grant.access_token, "session-1", secret, now)).toMatchObject({
      sub: "debug-agent", session_id: "session-1", scope: "session-diagnostics:read",
    });
    expect(grant.expires_at).toBe(new Date(now + 900_000).toISOString());
    expect(verifyDiagnosticsAccess(grant.access_token, "session-2", secret, now)).toBeNull();
    expect(verifyDiagnosticsAccess(grant.access_token, "session-1", secret, now + 900_000)).toBeNull();
    expect(verifyDiagnosticsAccess(grant.access_token, "session-1", secret, now - 1000)).toBeNull();
    expect(verifyDiagnosticsAccess(grant.access_token, "session-1", "other-secret-32-characters-long-enough", now)).toBeNull();
  });
  it("rejects tampering, malformed or oversized credentials without throwing", () => {
    const { access_token: token } = issueDiagnosticsAccess("session-1", "agent", secret, now);
    for (const invalid of ["", token + "x", token.replace("sd1", "sd2"), "x".repeat(3000), "sd1.e30.bad"])
      expect(verifyDiagnosticsAccess(invalid, "session-1", secret, now)).toBeNull();
  });
  it.each([
    { scope: "admin:write" }, { aud: "other-api" }, { exp: now / 1000 + 901 },
    { iat: now / 1000 + 1 }, { sub: "" }, { session_id: "*" }, { v: 2 },
  ])("rejects signed claims outside the allowed contract: %j", changes => {
    const token = issueDiagnosticsAccess("session-1", "agent", secret, now).access_token;
    const claims = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());
    const payload = Buffer.from(JSON.stringify({ ...claims, ...changes })).toString("base64url");
    const signature = createHmac("sha256", secret).update(`sd1.${payload}`).digest("base64url");
    expect(verifyDiagnosticsAccess(`sd1.${payload}.${signature}`, "session-1", secret, now)).toBeNull();
  });
  it("fails closed for missing or weak independent secrets and invalid identities", () => {
    for (const key of ["", "weak", " ".repeat(32)]) {
      expect(() => issueDiagnosticsAccess("session-1", "agent", key, now)).toThrow();
      expect(verifyDiagnosticsAccess("anything", "session-1", key, now)).toBeNull();
    }
    expect(() => issueDiagnosticsAccess("../secret", "agent", secret, now)).toThrow();
    for (const id of [".", ".."]) expect(() => issueDiagnosticsAccess(id, "agent", secret, now)).toThrow();
    expect(() => issueDiagnosticsAccess("session-1", "*", secret, now)).toThrow();
    expect(issueDiagnosticsAccess("session-1", "agent", secret, now).access_token)
      .not.toBe(issueDiagnosticsAccess("session-1", "agent", secret, now).access_token);
  });
});
