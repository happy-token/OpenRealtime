import { describe, expect, it } from "vitest";

import {
  buildPersonaSavePayload,
  buildPersonaSwitchPayload,
  diffPersonaFiles,
  isPersonaDraftDirty,
  personaDraftFromFiles,
} from "./persona-editor";

const original = [
  { filename: "SOUL.md" as const, content: "性格与边界" },
  { filename: "IDENTITY.md" as const, content: "# 知性温柔" },
];

describe("personaDraftFromFiles", () => {
  it("seeds a draft record from the loaded files", () => {
    expect(personaDraftFromFiles(original)).toEqual({
      "SOUL.md": "性格与边界",
      "IDENTITY.md": "# 知性温柔",
    });
  });
});

describe("diffPersonaFiles", () => {
  it("returns only the files whose draft content changed", () => {
    const draft = { "SOUL.md": "更新后的性格", "IDENTITY.md": "# 知性温柔" };
    expect(diffPersonaFiles(original, draft)).toEqual([
      { filename: "SOUL.md", content: "更新后的性格" },
    ]);
  });

  it("returns an empty list when nothing changed", () => {
    const draft = personaDraftFromFiles(original);
    expect(diffPersonaFiles(original, draft)).toEqual([]);
  });
});

describe("isPersonaDraftDirty", () => {
  it("is false for an unmodified draft", () => {
    expect(isPersonaDraftDirty(original, personaDraftFromFiles(original))).toBe(false);
  });

  it("is true once a draft field changes", () => {
    const draft = { ...personaDraftFromFiles(original), "SOUL.md": "更新" };
    expect(isPersonaDraftDirty(original, draft)).toBe(true);
  });
});

describe("buildPersonaSavePayload", () => {
  it("builds an updateFiles payload from the changed files only", () => {
    const draft = { ...personaDraftFromFiles(original), "SOUL.md": "更新" };
    expect(buildPersonaSavePayload(original, draft)).toEqual({
      operation: "updateFiles",
      files: [{ filename: "SOUL.md", content: "更新" }],
    });
  });
});

describe("buildPersonaSwitchPayload", () => {
  it("builds a switchPersona payload", () => {
    expect(buildPersonaSwitchPayload("sweet-sunshine")).toEqual({
      operation: "switchPersona",
      personaId: "sweet-sunshine",
    });
  });

  it("includes an avatarDisplayName when linking a previously-unlinked Avatar", () => {
    expect(buildPersonaSwitchPayload("sweet-sunshine", "新人")).toEqual({
      operation: "switchPersona",
      personaId: "sweet-sunshine",
      avatarDisplayName: "新人",
    });
  });
});
