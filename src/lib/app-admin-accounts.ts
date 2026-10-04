import { userDatabase, userTable } from "./user-db";
import type { WebUser } from "./user-session";

export interface AppAdminAccount {
  issuer: string;
  subject: string;
  granted_at: string;
  granted_by: string;
}

export async function isAppAdmin(user: WebUser): Promise<boolean> {
  const result = await userDatabase().query(
    `SELECT 1 FROM ${userTable("app_admin_accounts")} WHERE issuer = $1 AND subject = $2`,
    [user.issuer, user.subject],
  );
  return result.rows.length > 0;
}

export async function appAdminCount(): Promise<number> {
  const result = await userDatabase().query<{ count: string }>(
    `SELECT count(*) AS count FROM ${userTable("app_admin_accounts")}`,
  );
  return Number(result.rows[0]?.count ?? 0);
}

export async function listAppAdmins(): Promise<AppAdminAccount[]> {
  const result = await userDatabase().query<{ issuer: string; subject: string; granted_at: Date; granted_by: string }>(
    `SELECT issuer, subject, granted_at, granted_by FROM ${userTable("app_admin_accounts")} ORDER BY granted_at`,
  );
  return result.rows.map((row) => ({
    issuer: row.issuer,
    subject: row.subject,
    granted_at: row.granted_at.toISOString(),
    granted_by: row.granted_by,
  }));
}

export async function grantAppAdmin(target: WebUser, grantedBy: string): Promise<void> {
  await userDatabase().query(
    `INSERT INTO ${userTable("app_admin_accounts")} (issuer, subject, granted_by)
     VALUES ($1, $2, $3) ON CONFLICT (issuer, subject) DO NOTHING`,
    [target.issuer, target.subject, grantedBy],
  );
}

export async function revokeAppAdmin(target: WebUser): Promise<"deleted" | "last-admin" | "not-found"> {
  const connection = await userDatabase().connect();
  try {
    await connection.query("BEGIN");
    // Serialize list changes, including INSERTs, before checking the invariant.
    await connection.query(`LOCK TABLE ${userTable("app_admin_accounts")} IN EXCLUSIVE MODE`);
    const result = await connection.query<{ issuer: string; subject: string }>(
      `SELECT issuer, subject FROM ${userTable("app_admin_accounts")}`,
    );
    let outcome: "deleted" | "last-admin" | "not-found" = "not-found";
    if (result.rows.some((row) => row.issuer === target.issuer && row.subject === target.subject)) {
      if (result.rows.length <= 1) outcome = "last-admin";
      else {
        await connection.query(
          `DELETE FROM ${userTable("app_admin_accounts")} WHERE issuer = $1 AND subject = $2`,
          [target.issuer, target.subject],
        );
        outcome = "deleted";
      }
    }
    await connection.query("COMMIT");
    return outcome;
  } catch (error) {
    await connection.query("ROLLBACK");
    throw error;
  } finally {
    connection.release();
  }
}
