import type { AvatarPersonaFile } from "./avatar-persona";

export function personaDraftFromFiles(files: AvatarPersonaFile[]): Record<string, string> {
  return Object.fromEntries(files.map((file) => [file.filename, file.content]));
}

export function diffPersonaFiles(
  original: AvatarPersonaFile[],
  draft: Record<string, string>,
): AvatarPersonaFile[] {
  return original
    .filter((file) => draft[file.filename] !== undefined && draft[file.filename] !== file.content)
    .map((file) => ({ filename: file.filename, content: draft[file.filename] }));
}

export function isPersonaDraftDirty(original: AvatarPersonaFile[], draft: Record<string, string>): boolean {
  return diffPersonaFiles(original, draft).length > 0;
}

export function buildPersonaSavePayload(original: AvatarPersonaFile[], draft: Record<string, string>) {
  return { operation: "updateFiles" as const, files: diffPersonaFiles(original, draft) };
}

export function buildPersonaSwitchPayload(personaId: string, avatarDisplayName?: string) {
  return avatarDisplayName
    ? { operation: "switchPersona" as const, personaId, avatarDisplayName }
    : { operation: "switchPersona" as const, personaId };
}
