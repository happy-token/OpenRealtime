import { beforeEach, expect, it, vi } from "vitest";
import { findUserBySubject } from "./user-session";
const query = vi.hoisted(() => vi.fn());
vi.mock("./user-db", () => ({ userDatabase: () => ({ query }), userTable: () => '"voiceagent"."web_user_sessions"' }));
beforeEach(() => query.mockReset());
it("rejects a subject shared by multiple issuers instead of selecting the latest login", async () => {
  query.mockResolvedValue({ rows: [{ issuer: "a", subject: "same" }, { issuer: "b", subject: "same" }] });
  await expect(findUserBySubject("same")).rejects.toThrow("多个身份来源");
  expect(query.mock.calls[0][0]).toContain("GROUP BY issuer, subject");
});
it("looks up the exact issuer and returns null for an unknown account", async () => {
  query.mockResolvedValue({ rows: [{ issuer: "b", subject: "same" }] });
  expect(await findUserBySubject("same", "b")).toEqual({ issuer: "b", subject: "same" });
  expect(query.mock.calls[0][1]).toEqual(["same", "b"]);
  query.mockResolvedValue({ rows: [] });
  expect(await findUserBySubject("absent", "b")).toBeNull();
});
