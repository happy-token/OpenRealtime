export const AVATAR_PERSONA_FILENAMES = ["AGENTS.md", "SOUL.md", "IDENTITY.md"] as const;
export const REQUIRED_AVATAR_PERSONA_FILENAMES = ["SOUL.md", "IDENTITY.md"] as const;

export type AvatarPersonaFile = {
  filename: (typeof AVATAR_PERSONA_FILENAMES)[number];
  content: string;
};

export type AvatarPersonaProfile = {
  avatarId: string;
  personaId: string;
  personaName: string;
  avatarDisplayName: string;
  files: AvatarPersonaFile[];
  linkedAvatarIds: string[];
};

export type PersonaProfile = {
  personaId: string;
  personaName: string;
  files: AvatarPersonaFile[];
  linkedAvatarIds: string[];
};

export type PersonaSummary = {
  personaId: string;
  personaName: string;
  linkedAvatarIds: string[];
};

export function avatarPersonaSelectionId(config: {
  renderPath: "hosted" | "segmented" | "orchestrated";
  avatarProfileId: string;
  segmentedAvatarId: string;
}) {
  return config.renderPath !== "hosted"
    ? config.segmentedAvatarId
    : config.avatarProfileId;
}

export const PERSONA_CREATE_OPTION_VALUE = "__create_persona__";
export const PERSONA_UNLINKED_OPTION_VALUE = "";

export interface PersonaSelectOption {
  value: string;
  label: string;
  description?: string;
}

/**
 * Builds the option list for a Persona-picker dropdown: a create-Persona
 * entry first, an "unlinked" placeholder when nothing is linked yet, then
 * one row per existing Persona.
 */
export function personaSelectOptions(
  personas: readonly PersonaSummary[],
  linkedPersonaId: string | null,
): PersonaSelectOption[] {
  const options: PersonaSelectOption[] = [
    { value: PERSONA_CREATE_OPTION_VALUE, label: "+ 创建 Persona" },
  ];
  if (!linkedPersonaId) {
    options.push({ value: PERSONA_UNLINKED_OPTION_VALUE, label: "未关联 Persona" });
  }
  for (const persona of personas) {
    options.push({
      value: persona.personaId,
      label: persona.personaName,
      description: `关联 ${persona.linkedAvatarIds.length} 个数字人`,
    });
  }
  return options;
}
