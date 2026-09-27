import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createRole, deleteRole, findRole, listRoles, updateRole } from "./role-catalog-repository";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function temporaryRoot() {
  const root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-roles-"));
  roots.push(root);
  return root;
}

describe("role catalog repository", () => {
  it("persists role provider overrides and can return to provider defaults", async () => {
    const root = await temporaryRoot();
    const role = await createRole({
      displayName: "供应商测试",
      asrProvider: "dashscope",
      llmProvider: "openai",
    }, root);
    expect(await findRole(role.role_id, root)).toMatchObject({
      asr_provider: "dashscope",
      llm_provider: "openai",
    });

    await updateRole(role.role_id, { asrProvider: null, llmProvider: null }, root);
    expect(await findRole(role.role_id, root)).toMatchObject({
      asr_provider: null,
      llm_provider: null,
    });
  });

  it("prefers offline as the default when it is enabled and no mode was chosen", async () => {
    const root = await temporaryRoot();
    await createRole({ displayName: "离线角色", enabledModes: ["conversation", "offline"] }, root);
    const stored = JSON.parse(await readFile(path.join(root, "roles.json"), "utf8")) as Array<Record<string, unknown>>;
    expect(stored[0].default_mode).toBe("offline");
  });

  it("always exposes the default assistant and migrates linked avatar roles", async () => {
    const roles = await listRoles(await temporaryRoot());
    expect(roles[0]).toMatchObject({
      role_id: "default-assistant",
      default_mode: "conversation",
      enabled_modes: ["conversation"],
      memory_enabled: true,
    });
    expect(roles.some((role) => role.avatar_id && role.persona_id)).toBe(true);
  });

  it("persists selected resources while resolving modes from current avatar capabilities", async () => {
    const root = await temporaryRoot();
    const role = await createRole({
      displayName: "产品顾问",
      voiceProvider: "doubao",
      voiceId: "zh_female_qingxinnvsheng_uranus_bigtts",
      voiceDialect: "sichuan",
      personaId: "intellectual-warmth",
      avatarId: "avatar-zhaoning",
      enabledModes: ["conversation", "offline", "lip-sync"],
      defaultMode: "offline",
      defaultSelections: { offline: { action_id: "action-test", talking_variant_id: "talk-test" } },
      memoryEnabled: false,
      toolIds: ["tool-current-time", "tool-web-search"],
    }, root);
    expect(role).toMatchObject({
      display_name: "产品顾问",
      voice_provider: "doubao",
      voice_dialect: "sichuan",
      persona_id: "intellectual-warmth",
      avatar_id: "avatar-zhaoning",
      enabled_modes: ["conversation"],
      default_mode: "conversation",
      memory_enabled: false,
      tool_ids: ["tool-current-time", "tool-web-search"],
    });
    expect(await findRole(role.role_id, root)).toMatchObject({ display_name: "产品顾问" });
    const stored = JSON.parse(await readFile(path.join(root, "roles.json"), "utf8")) as Array<Record<string, unknown>>;
    expect(stored[0]).toMatchObject({
      persona_id: "intellectual-warmth",
      voice_dialect: "sichuan",
      avatar_id: "avatar-zhaoning",
      default_mode: "offline",
      default_selections: { offline: { action_id: "action-test", talking_variant_id: "talk-test" } },
      memory_enabled: false,
      tool_ids: ["tool-current-time", "tool-web-search"],
    });
  });

  it("materializes and updates a migrated role without losing inferred avatar metadata", async () => {
    const root = await temporaryRoot();
    const migrated = (await listRoles(root)).find((role) => role.avatar_id && role.persona_id);
    expect(migrated).toBeTruthy();
    const updated = await updateRole(migrated!.role_id, {
      displayName: "更新后的角色",
      memoryEnabled: false,
      enabledModes: ["conversation"],
      defaultMode: "conversation",
    }, root);
    expect(updated).toMatchObject({
      display_name: "更新后的角色",
      avatar_id: migrated!.avatar_id,
      avatar_image_url: migrated!.avatar_image_url,
      memory_enabled: false,
    });
    const stored = JSON.parse(await readFile(path.join(root, "roles.json"), "utf8")) as Array<Record<string, unknown>>;
    expect(stored[0]).not.toHaveProperty("avatar_image_url");
    expect(stored[0]).not.toHaveProperty("persona_name");
  });

  it("soft-deletes a role while protecting the built-in default assistant", async () => {
    const root = await temporaryRoot();
    const role = await createRole({ displayName: "待删除角色" }, root);
    await expect(deleteRole(role.role_id, root)).resolves.toBe(true);
    await expect(findRole(role.role_id, root)).resolves.toBeNull();
    await expect(deleteRole("default-assistant", root)).rejects.toThrow("默认助手不能删除");
    const stored = JSON.parse(await readFile(path.join(root, "roles.json"), "utf8")) as Array<Record<string, unknown>>;
    expect(stored[0].deleted_at).toEqual(expect.any(String));
  });
});
