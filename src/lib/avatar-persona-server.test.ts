import { mkdtemp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  createPersona,
  archivePersona,
  listPersonas,
  readAvatarPersonaProfile,
  readPersonaProfile,
  renamePersona,
  switchAvatarPersona,
  writeAvatarPersonaFiles,
  writePersonaIntro,
} from "./avatar-persona-server";

async function makeRoot() {
  return mkdtemp(path.join(tmpdir(), "openrealtime-persona-"));
}

async function seedPersona(root: string, personaId: string, identityHeading: string) {
  const personaDir = path.join(root, "config", "personas", personaId);
  await mkdir(personaDir, { recursive: true });
  await writeFile(path.join(personaDir, "IDENTITY.md"), `# ${identityHeading}\n\n身份定义`);
  await writeFile(path.join(personaDir, "SOUL.md"), "性格与边界");
}

async function seedLinks(root: string, links: Record<string, { personaId: string; avatarDisplayName: string }>) {
  await mkdir(path.join(root, "config"), { recursive: true });
  await writeFile(
    path.join(root, "config", "avatar-persona-links.json"),
    JSON.stringify({ version: 2, links }, null, 2),
  );
}

describe("readAvatarPersonaProfile", () => {
  it("reads the Avatar-linked files in the OpenClaw Persona order", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "openrealtime-persona-"));
    const personaDir = path.join(root, "config", "personas", "intellectual-warmth");
    await mkdir(personaDir, { recursive: true });
    await writeFile(path.join(root, "config", "avatar-persona-links.json"), JSON.stringify({
      version: 2,
      links: {
        "avatar-zhaoning": {
          personaId: "intellectual-warmth",
          avatarDisplayName: "昭宁",
        },
      },
    }));
    await writeFile(path.join(personaDir, "IDENTITY.md"), "# 知性温柔\n\n身份定义");
    await writeFile(path.join(personaDir, "AGENTS.md"), "交互规则");
    await writeFile(path.join(personaDir, "SOUL.md"), "性格与边界");

    await expect(readAvatarPersonaProfile("avatar-zhaoning", root)).resolves.toEqual({
      avatarId: "avatar-zhaoning",
      personaId: "intellectual-warmth",
      personaName: "知性温柔",
      avatarDisplayName: "昭宁",
      files: [
        { filename: "AGENTS.md", content: "交互规则" },
        { filename: "SOUL.md", content: "性格与边界" },
        { filename: "IDENTITY.md", content: "# 知性温柔\n\n身份定义" },
      ],
      linkedAvatarIds: ["avatar-zhaoning"],
    });
  });

  it("does not resolve path-like Avatar IDs", async () => {
    await expect(readAvatarPersonaProfile("../../outside")).rejects.toThrow("Avatar ID 无效");
  });

  it("keeps all seven selected Avatar profiles complete", async () => {
    const expected = new Map([
      ["default-anam", ["Shuchang", "知性温柔"]],
      ["shuchang", ["Shuchang", "知性温柔"]],
      ["companion", ["陪伴", "柔光纯欲"]],
      ["avatar-zhaoning", ["昭宁", "知性温柔"]],
      ["avatar-meichuqing", ["梅初晴", "甜美元气"]],
      ["avatar-qingyun", ["清韫", "忧郁薄雾"]],
      ["avatar-selin", ["瑟琳", "浪漫法式"]],
      ["avatar-shiruoshui", ["施若水", "柔光纯欲"]],
      ["avatar-zhaoyue", ["曌月", "冷艳都市"]],
      ["avatar-qingzhao", ["清照", "忧郁薄雾"]],
    ]);

    for (const [avatarId, [avatarDisplayName, personaName]] of expected) {
      const profile = await readAvatarPersonaProfile(avatarId);
      expect(profile?.avatarDisplayName).toBe(avatarDisplayName);
      expect(profile?.personaName).toBe(personaName);
      expect(profile?.files.map((file) => file.filename)).toEqual([
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
      ]);
    }
  });
});

describe("listPersonas", () => {
  it("uses identity positioning until a separate card intro is saved", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");
    const identityPath = path.join(root, "config", "personas", "intellectual-warmth", "IDENTITY.md");
    await writeFile(identityPath, "# 知性温柔\n\n- Persona 定位：成熟的文化策展人与阅读顾问。");

    expect((await listPersonas(root))[0].intro).toBe("成熟的文化策展人与阅读顾问。");
    await writePersonaIntro("intellectual-warmth", "温和、清醒，擅长陪你理清复杂问题。", root);
    expect((await listPersonas(root))[0].intro).toBe("温和、清醒，擅长陪你理清复杂问题。");
    expect((await readPersonaProfile("intellectual-warmth", root))?.intro).toBe("温和、清醒，擅长陪你理清复杂问题。");
  });
  it("lists every Persona directory with its identity heading as the name", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");
    await seedPersona(root, "sweet-sunshine", "甜美元气");

    await expect(listPersonas(root)).resolves.toEqual([
      { personaId: "intellectual-warmth", personaName: "知性温柔", linkedAvatarIds: [] },
      { personaId: "sweet-sunshine", personaName: "甜美元气", linkedAvatarIds: [] },
    ]);
  });

  it("populates linkedAvatarIds from the links file", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");
    await seedLinks(root, {
      "avatar-zhaoning": { personaId: "intellectual-warmth", avatarDisplayName: "昭宁" },
      "avatar-meichuqing": { personaId: "intellectual-warmth", avatarDisplayName: "梅初晴" },
    });

    const [persona] = await listPersonas(root);
    expect(persona.linkedAvatarIds).toEqual(["avatar-meichuqing", "avatar-zhaoning"]);
  });

  it("returns an empty list when no Persona directory exists", async () => {
    const root = await makeRoot();
    await expect(listPersonas(root)).resolves.toEqual([]);
  });
});

describe("readPersonaProfile", () => {
  it("reads a Persona's files by ID regardless of Avatar links", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");
    await seedLinks(root, {
      "avatar-zhaoning": { personaId: "intellectual-warmth", avatarDisplayName: "昭宁" },
    });

    await expect(readPersonaProfile("intellectual-warmth", root)).resolves.toEqual({
      personaId: "intellectual-warmth",
      personaName: "知性温柔",
      files: [
        { filename: "SOUL.md", content: "性格与边界" },
        { filename: "IDENTITY.md", content: "# 知性温柔\n\n身份定义" },
      ],
      linkedAvatarIds: ["avatar-zhaoning"],
    });
  });

  it("returns null for a Persona directory that does not exist", async () => {
    const root = await makeRoot();
    await expect(readPersonaProfile("does-not-exist", root)).resolves.toBeNull();
  });
});

describe("createPersona", () => {
  it("creates a brand-new Persona directory from the given files", async () => {
    const root = await makeRoot();

    await createPersona("brand-new", [
      { filename: "IDENTITY.md", content: "# 全新人格\n\n身份定义" },
      { filename: "SOUL.md", content: "性格与边界" },
    ], root);

    await expect(readPersonaProfile("brand-new", root)).resolves.toEqual({
      personaId: "brand-new",
      personaName: "全新人格",
      files: [
        { filename: "SOUL.md", content: "性格与边界" },
        { filename: "IDENTITY.md", content: "# 全新人格\n\n身份定义" },
      ],
      linkedAvatarIds: [],
    });
  });

  it("rejects creating a Persona ID that already exists", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");

    await expect(createPersona("intellectual-warmth", [
      { filename: "IDENTITY.md", content: "# 覆盖\n\n身份定义" },
      { filename: "SOUL.md", content: "性格与边界" },
    ], root)).rejects.toThrow("Persona 已存在");
  });

  it("rejects creating a Persona missing required files", async () => {
    const root = await makeRoot();

    await expect(createPersona("incomplete", [
      { filename: "AGENTS.md", content: "交互规则" },
    ], root)).rejects.toThrow("缺少必需文件");
  });
});

describe("Persona management", () => {
  it("renames only the display heading and preserves the Persona ID and content", async () => {
    const root = await makeRoot();
    await seedPersona(root, "custom-persona", "旧名称");

    const updated = await renamePersona("custom-persona", " 新名称 ", root);

    expect(updated).toMatchObject({ personaId: "custom-persona", personaName: "新名称" });
    await expect(readFile(path.join(root, "config", "personas", "custom-persona", "IDENTITY.md"), "utf8"))
      .resolves.toBe("# 新名称\n\n身份定义");
    await expect(renamePersona("custom-persona", " ", root)).rejects.toThrow("人设名称无效");
  });

  it("archives an unused custom Persona without permanently deleting its files", async () => {
    const root = await makeRoot();
    await seedPersona(root, "custom-persona", "自定义");

    await archivePersona("custom-persona", root);

    await expect(readPersonaProfile("custom-persona", root)).resolves.toBeNull();
    const [entry] = await readdir(path.join(root, ".openrealtime", "persona-trash"));
    expect(entry).toMatch(/^custom-persona-/);
    await expect(readFile(path.join(root, ".openrealtime", "persona-trash", entry, "IDENTITY.md"), "utf8"))
      .resolves.toContain("# 自定义");
  });

  it("protects built-in and referenced Personas from deletion", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "内置");
    await expect(archivePersona("intellectual-warmth", root)).rejects.toThrow("内置人设不能删除");

    await seedPersona(root, "custom-linked", "已关联");
    await seedLinks(root, { "avatar-one": { personaId: "custom-linked", avatarDisplayName: "形象" } });
    await expect(archivePersona("custom-linked", root)).rejects.toThrow("仍被数字人或角色使用");

    await seedPersona(root, "custom-role", "角色使用");
    const catalog = path.join(root, ".openrealtime", "role-catalog");
    await mkdir(catalog, { recursive: true });
    await writeFile(path.join(catalog, "roles.json"), JSON.stringify([{ persona_id: "custom-role", deleted_at: null }]));
    await expect(archivePersona("custom-role", root)).rejects.toThrow("仍被数字人或角色使用");

    await seedPersona(root, "custom-personal-role", "个人角色使用");
    const personalRoles = path.join(root, ".openrealtime", "personal-motion", "owner-one", "roles");
    await mkdir(personalRoles, { recursive: true });
    await writeFile(path.join(personalRoles, "catalog.json"), JSON.stringify([{ persona_id: "custom-personal-role", deleted_at: null }]));
    await expect(archivePersona("custom-personal-role", root)).rejects.toThrow("仍被数字人或角色使用");
  });
});

describe("writeAvatarPersonaFiles", () => {
  it("writes the given files atomically", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");

    await writeAvatarPersonaFiles("intellectual-warmth", [
      { filename: "SOUL.md", content: "更新后的性格" },
    ], root);

    await expect(
      readFile(path.join(root, "config", "personas", "intellectual-warmth", "SOUL.md"), "utf8"),
    ).resolves.toBe("更新后的性格");
  });

  it("rejects an oversized file", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");

    await expect(writeAvatarPersonaFiles("intellectual-warmth", [
      { filename: "SOUL.md", content: "a".repeat(8_001) },
    ], root)).rejects.toThrow("Persona 文件过大");
  });

  it("rejects an oversized total across files", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");

    await expect(writeAvatarPersonaFiles("intellectual-warmth", [
      { filename: "AGENTS.md", content: "a".repeat(8_000) },
      { filename: "SOUL.md", content: "b".repeat(8_000) },
      { filename: "IDENTITY.md", content: "c".repeat(1) },
    ], root)).rejects.toThrow("Persona 配置总长度过大");
  });

  it("rejects an invalid Persona ID", async () => {
    const root = await makeRoot();
    await expect(writeAvatarPersonaFiles("../outside", [
      { filename: "SOUL.md", content: "x" },
    ], root)).rejects.toThrow("Persona ID 无效");
  });
});

describe("switchAvatarPersona", () => {
  it("retargets an existing Avatar link to a different Persona", async () => {
    const root = await makeRoot();
    await seedPersona(root, "intellectual-warmth", "知性温柔");
    await seedPersona(root, "sweet-sunshine", "甜美元气");
    await seedLinks(root, {
      "avatar-zhaoning": { personaId: "intellectual-warmth", avatarDisplayName: "昭宁" },
    });

    await switchAvatarPersona("avatar-zhaoning", "sweet-sunshine", undefined, root);

    const links = JSON.parse(await readFile(path.join(root, "config", "avatar-persona-links.json"), "utf8"));
    expect(links.links["avatar-zhaoning"]).toEqual({
      personaId: "sweet-sunshine",
      avatarDisplayName: "昭宁",
    });
  });

  it("rejects switching an unlinked Avatar without a display name", async () => {
    const root = await makeRoot();
    await seedPersona(root, "sweet-sunshine", "甜美元气");
    await seedLinks(root, {});

    await expect(
      switchAvatarPersona("avatar-unknown", "sweet-sunshine", undefined, root),
    ).rejects.toThrow("缺少 Avatar 显示名称");
  });

  it("creates a new link for a previously-unlinked Avatar given a display name", async () => {
    const root = await makeRoot();
    await seedPersona(root, "sweet-sunshine", "甜美元气");
    await seedLinks(root, {});

    await switchAvatarPersona("avatar-unknown", "sweet-sunshine", "新人", root);

    const links = JSON.parse(await readFile(path.join(root, "config", "avatar-persona-links.json"), "utf8"));
    expect(links.links["avatar-unknown"]).toEqual({
      personaId: "sweet-sunshine",
      avatarDisplayName: "新人",
    });
  });

  it("rejects switching to a Persona missing required files", async () => {
    const root = await makeRoot();
    await mkdir(path.join(root, "config", "personas", "incomplete"), { recursive: true });
    await seedLinks(root, {
      "avatar-zhaoning": { personaId: "intellectual-warmth", avatarDisplayName: "昭宁" },
    });

    await expect(
      switchAvatarPersona("avatar-zhaoning", "incomplete", undefined, root),
    ).rejects.toThrow("缺少必需文件");
  });
});
