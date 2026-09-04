import { describe, expect, it } from "vitest";

import {
  avatarPersonaSelectionId,
  PERSONA_CREATE_OPTION_VALUE,
  personaSelectOptions,
  type PersonaSummary,
} from "./avatar-persona";

const config = {
  renderPath: "hosted" as const,
  avatarProfileId: "default-anam",
  segmentedAvatarId: "shuchang",
};

describe("avatarPersonaSelectionId", () => {
  it("selects the hosted built-in Avatar association", () => {
    expect(avatarPersonaSelectionId(config)).toBe("default-anam");
  });

  it("selects the segmented built-in Avatar association", () => {
    expect(avatarPersonaSelectionId({ ...config, renderPath: "segmented" })).toBe("shuchang");
  });
});

describe("personaSelectOptions", () => {
  const personas: PersonaSummary[] = [
    { personaId: "sweet-sunshine", personaName: "暖阳", linkedAvatarIds: ["default-anam"] },
    { personaId: "cool-breeze", personaName: "清风", linkedAvatarIds: [] },
  ];

  it("always puts the create-Persona row first", () => {
    const options = personaSelectOptions(personas, "sweet-sunshine");
    expect(options[0]).toEqual({ value: PERSONA_CREATE_OPTION_VALUE, label: "+ 创建 Persona" });
  });

  it("adds an 'unlinked' placeholder only when nothing is linked", () => {
    const unlinked = personaSelectOptions(personas, null);
    expect(unlinked[1]).toEqual({ value: "", label: "未关联 Persona" });

    const linked = personaSelectOptions(personas, "sweet-sunshine");
    expect(linked.some((option) => option.value === "")).toBe(false);
  });

  it("lists one option per Persona with a linked-avatar-count description", () => {
    const options = personaSelectOptions(personas, "sweet-sunshine");
    expect(options).toContainEqual({
      value: "sweet-sunshine",
      label: "暖阳",
      description: "关联 1 个数字人",
    });
    expect(options).toContainEqual({
      value: "cool-breeze",
      label: "清风",
      description: "关联 0 个数字人",
    });
  });
});
