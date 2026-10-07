import { createHash, createHmac } from "node:crypto";
import type { WebUser } from "./user-session";
import { currentAppAdmin } from "./admin-server";
import { isDiagnosticSessionId } from "./diagnostics-access";
import { recordingError } from "./recording-access-server";

function preservationOrigin(request: Request): string | null {
  try {
    const url = new URL(request.url), host = request.headers.get("host");
    // Next may normalize 127.0.0.1 to localhost; use the actual HTTP authority.
    // Forwarded headers and Referer cannot authorize a mutation.
    if (host !== null) {
      if (!/^(?:[A-Za-z0-9.-]+|\[[A-Fa-f0-9:]+\])(?::[0-9]+)?$/.test(host)) return null;
      return new URL(`${url.protocol}//${host}`).origin;
    }
    return url.origin;
  } catch { return null; }
}

/** Write access never accepts an Agent grant or falls back from Authorization. */
export async function recordingPreservationAdmin(request: Request, sessionId: string): Promise<WebUser | Response> {
  if (request.headers.has("authorization")) return recordingError(403, "Agent 凭据仅允许读取录音");
  const origin = request.headers.get("origin"), site = request.headers.get("sec-fetch-site");
  if (!origin || origin !== preservationOrigin(request) || (site && site !== "same-origin")) return recordingError(403, "请求来源无效");
  if (!isDiagnosticSessionId(sessionId)) return recordingError(400, "Session ID 无效");
  try { return await currentAppAdmin(request) ?? recordingError(403, "未授权"); }
  catch { return recordingError(503, "管理员权限服务暂时不可用"); }
}

/** Domain-separated private transport proof; neither it nor the root key reaches a browser. */
export function preservationWriteProof(user: WebUser, sessionId: string, now = Date.now()) {
  const encoded = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded || !/^[A-Za-z0-9_-]+={0,2}$/.test(encoded)) throw new Error("preservation-not-configured");
  const root = Buffer.from(encoded, "base64url");
  if (root.length !== 32 || root.toString("base64url") !== encoded.replace(/=+$/, "")) throw new Error("preservation-not-configured");
  const actor = createHash("sha256").update(JSON.stringify([user.issuer, user.subject])).digest("hex");
  const body = JSON.stringify({ actor_id: actor }), timestamp = String(Math.floor(now / 1000));
  const key = createHmac("sha256", root).update("openrealtime/session-recording-preservation/key/v1").digest();
  const signature = createHmac("sha256", key).update(`session-recording-preservation-v1\0${timestamp}\0${sessionId}\0${body}`).digest("hex");
  return { body, headers: { "Content-Type": "application/json", "X-Recording-Preservation-Timestamp": timestamp, "X-Recording-Preservation-Signature": signature } };
}
