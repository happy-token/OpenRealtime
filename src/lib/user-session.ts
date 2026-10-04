import { createHash, randomBytes } from "node:crypto";
import { userDatabase, userTable } from "./user-db";

export const USER_SESSION_COOKIE = "openrealtime_user_session";
export const USER_SESSION_SECONDS = 8 * 60 * 60;

export interface WebUser {
  issuer: string;
  subject: string;
}

function tokenHash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export async function createUserSession(user: WebUser): Promise<string> {
  const token = randomBytes(32).toString("base64url");
  await userDatabase().query(
    `INSERT INTO ${userTable("web_user_sessions")} (token_hash, issuer, subject, expires_at)
     VALUES ($1, $2, $3, now() + ($4 * interval '1 second'))`,
    [tokenHash(token), user.issuer, user.subject, USER_SESSION_SECONDS],
  );
  return token;
}

export async function userFromSessionToken(token: string | undefined): Promise<WebUser | null> {
  if (!token || !/^[A-Za-z0-9_-]{40,64}$/.test(token)) return null;
  const result = await userDatabase().query<{ issuer: string; subject: string }>(
    `SELECT issuer, subject FROM ${userTable("web_user_sessions")}
     WHERE token_hash = $1 AND expires_at > now()`,
    [tokenHash(token)],
  );
  return result.rows[0] || null;
}

export async function userFromRequest(request: Request): Promise<WebUser | null> {
  const cookie = request.headers.get("cookie")?.split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${USER_SESSION_COOKIE}=`));
  if (!cookie) return null;
  let token: string;
  try {
    token = decodeURIComponent(cookie.slice(USER_SESSION_COOKIE.length + 1));
  } catch {
    return null;
  }
  return userFromSessionToken(token);
}

export async function findUserBySubject(subject: string, issuer?: string): Promise<WebUser | null> {
  // Identity lookup only (not an auth check): an admin grant should resolve a
  // target account even if their session has since expired.
  const result = await userDatabase().query<{ issuer: string; subject: string }>(
    `SELECT issuer, subject FROM ${userTable("web_user_sessions")}
     WHERE subject = $1 AND ($2::text IS NULL OR issuer = $2)
     GROUP BY issuer, subject
     LIMIT 2`,
    [subject, issuer ?? null],
  );
  if (result.rows.length > 1) throw new Error("账号 ID 对应多个身份来源，请填写 issuer");
  return result.rows[0] || null;
}

export async function revokeUserSession(token: string | undefined): Promise<void> {
  if (!token || !/^[A-Za-z0-9_-]{40,64}$/.test(token)) return;
  await userDatabase().query(
    `DELETE FROM ${userTable("web_user_sessions")} WHERE token_hash = $1`,
    [tokenHash(token)],
  );
}
