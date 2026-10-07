import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const ID = /^[A-Za-z0-9._:-]{1,128}$/;
const AGENT_ID = /^[A-Za-z0-9._:-]{1,64}$/;
const TTL_SECONDS = 15 * 60;
const AUDIENCE = "openrealtime-session-diagnostics";

interface DiagnosticIdentity {
  v: 1;
  aud: typeof AUDIENCE;
  scope: "session-diagnostics:read";
  sub: string;
  session_id: string;
  iat: number;
  exp: number;
  nonce: string;
}

export function isDiagnosticSessionId(sessionId: string): boolean {
  return ID.test(sessionId) && sessionId !== "." && sessionId !== "..";
}

function validSecret(secret: string | undefined): secret is string {
  return typeof secret === "string" && secret.trim().length >= 32;
}

export function issueDiagnosticsAccess(sessionId: string, agentId: string, secret: string | undefined, now = Date.now()) {
  if (!validSecret(secret) || !isDiagnosticSessionId(sessionId) || !AGENT_ID.test(agentId) || !Number.isFinite(now)) {
    throw new Error("Diagnostic access configuration or identity is invalid");
  }
  const issued = Math.floor(now / 1000);
  const identity: DiagnosticIdentity = {
    v: 1, aud: AUDIENCE, scope: "session-diagnostics:read", sub: agentId,
    session_id: sessionId, iat: issued, exp: issued + TTL_SECONDS,
    nonce: randomBytes(20).toString("hex"),
  };
  const payload = Buffer.from(JSON.stringify(identity)).toString("base64url");
  const signed = `sd1.${payload}`;
  const signature = createHmac("sha256", secret).update(signed).digest("base64url");
  return { access_token: `${signed}.${signature}`, token_type: "Bearer" as const,
    scope: identity.scope, session_id: sessionId, agent_id: agentId,
    expires_at: new Date(identity.exp * 1000).toISOString() };
}

/** A separate, exact-session read grant; never a browser/admin credential. */
export function verifyDiagnosticsAccess(token: string, sessionId: string, secret: string | undefined, now = Date.now()): DiagnosticIdentity | null {
  if (!validSecret(secret) || token.length > 2048 || !isDiagnosticSessionId(sessionId) || !Number.isFinite(now)) return null;
  const match = /^sd1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]{43})$/.exec(token);
  if (!match) return null;
  const expected = createHmac("sha256", secret).update(`sd1.${match[1]}`).digest("base64url");
  if (!timingSafeEqual(Buffer.from(match[2]), Buffer.from(expected))) return null;
  try {
    const identity = JSON.parse(Buffer.from(match[1], "base64url").toString("utf8")) as DiagnosticIdentity;
    const seconds = Math.floor(now / 1000);
    if (!identity || identity.v !== 1 || identity.aud !== AUDIENCE || identity.scope !== "session-diagnostics:read"
      || typeof identity.sub !== "string" || !AGENT_ID.test(identity.sub) || identity.session_id !== sessionId
      || typeof identity.nonce !== "string" || !/^[a-f0-9]{40}$/.test(identity.nonce)
      || !Number.isSafeInteger(identity.iat) || !Number.isSafeInteger(identity.exp)
      || identity.iat > seconds || identity.exp <= seconds || identity.exp <= identity.iat
      || identity.exp - identity.iat > TTL_SECONDS) return null;
    return identity;
  } catch { return null; }
}
