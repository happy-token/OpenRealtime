import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { avatarIdFromHostedRoleId, hostedAvatarRoleId } from "./hosted-avatar-role-id";
import { getHostedAvatarSettings, saveHostedAvatarSettings } from "./hosted-avatar-settings-repository";

const roots: string[] = [];
afterEach(async () => { for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true }); });

describe("hosted avatar settings", () => {
  it("uses a distinct role scope for each hosted avatar", () => {
    expect(hostedAvatarRoleId("avatar-one")).toBe("hosted-avatar-avatar-one");
    expect(avatarIdFromHostedRoleId("hosted-avatar-avatar-one")).toBe("avatar-one");
    expect(avatarIdFromHostedRoleId("role-one")).toBeNull();
    expect(() => hostedAvatarRoleId("../unsafe")).toThrow();
  });

  it("keeps memory settings separated by owner and avatar", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "hosted-avatar-settings-"));
    roots.push(root);
    await saveHostedAvatarSettings("alice", "avatar-one", true, ["tool-one"], root);
    expect((await getHostedAvatarSettings("alice", "avatar-one", root))?.memory_enabled).toBe(true);
    expect((await getHostedAvatarSettings("alice", "avatar-one", root))?.tool_ids).toEqual(["tool-one"]);
    expect(await getHostedAvatarSettings("bob", "avatar-one", root)).toBeNull();
    expect(await getHostedAvatarSettings("alice", "avatar-two", root)).toBeNull();
  });
});
