import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getToolPermissions, saveToolPermissions } from "./tool-permission-repository";
import { effectiveToolPermission } from "./tool-permission-types";

let root: string;
beforeEach(async () => { root = await mkdtemp(path.join(tmpdir(), "tool-permissions-")); });
afterEach(async () => { await rm(root, { recursive: true, force: true }); });

describe("user tool permission settings", () => {
  it("defaults to full and isolates owners and roles", async () => {
    expect((await getToolPermissions("alice", root)).mode).toBe("full");
    await saveToolPermissions("alice", "balanced", null, root);
    await saveToolPermissions("alice", "confirm", "role-a", root);
    expect(effectiveToolPermission(await getToolPermissions("alice", root), "role-a")).toBe("confirm");
    expect(effectiveToolPermission(await getToolPermissions("alice", root), "role-b")).toBe("balanced");
    expect((await getToolPermissions("bob", root)).mode).toBe("full");
    await saveToolPermissions("alice", null, "role-a", root);
    expect(effectiveToolPermission(await getToolPermissions("alice", root), "role-a")).toBe("balanced");
  });
  it("serializes concurrent updates and uses the Python-compatible schema", async () => {
    await Promise.all([saveToolPermissions("alice", "confirm", "role-a", root), saveToolPermissions("alice", "balanced", "role-b", root)]);
    const saved = await getToolPermissions("alice", root);
    expect(saved.roleOverrides).toEqual({ "role-a": "confirm", "role-b": "balanced" });
    const disk = JSON.parse(await readFile(path.join(root, "settings.json"), "utf8"));
    expect(disk.version).toBe(1);
    expect(disk.records[0].owner_id).toBe("alice");
    expect(disk.records[0].role_overrides).toEqual(saved.roleOverrides);
  });
  it("does not overwrite corrupt settings or interpret prototype members as overrides", async () => {
    await writeFile(path.join(root, "settings.json"), "{broken");
    await expect(saveToolPermissions("alice", "full", null, root)).rejects.toThrow();
    expect(effectiveToolPermission({ mode: "balanced", roleOverrides: {}, updatedAt: null }, "constructor")).toBe("balanced");
  });
});
