import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { grantAppAdmin, listAppAdmins, revokeAppAdmin } from "./app-admin-accounts";

let pool: Pool;
const schema = `admin_test_${randomUUID().replaceAll("-", "")}`;
vi.mock("./user-db", () => ({
  userDatabase: () => pool,
  userTable: () => `"${schema}".app_admin_accounts`,
}));
const enabled = process.env.RUN_ADMIN_POSTGRES_TEST === "1";
beforeAll(async () => {
  if (!enabled) return;
  pool = new Pool({ connectionString: process.env.VOICEAGENT_POSTGRES_DSN });
  await pool.query(`CREATE SCHEMA "${schema}"`);
  await pool.query(`CREATE TABLE "${schema}".app_admin_accounts (
    issuer text NOT NULL, subject text NOT NULL, granted_by text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (issuer, subject))`);
});
afterAll(async () => {
  if (!pool) return;
  try { await pool.query(`DROP SCHEMA "${schema}" CASCADE`); }
  finally { await pool.end(); }
});
it.skipIf(!enabled)("serializes concurrent revokes and preserves the final admin across issuers", async () => {
  const a = { issuer: "issuer-a", subject: "same-id" };
  const b = { issuer: "issuer-b", subject: "same-id" };
  await grantAppAdmin(a, "test");
  await grantAppAdmin(b, "test");
  const outcomes = await Promise.all([revokeAppAdmin(a), revokeAppAdmin(b)]);
  expect(outcomes.sort()).toEqual(["deleted", "last-admin"]);
  const remaining = await listAppAdmins();
  expect(remaining).toHaveLength(1);
  expect(await revokeAppAdmin(remaining[0])).toBe("last-admin");
  expect(await revokeAppAdmin({ issuer: "absent", subject: "same-id" })).toBe("not-found");
});
