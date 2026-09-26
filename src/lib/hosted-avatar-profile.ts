import { DEFAULT_TTS_VOICE, isTtsDialect, isTtsVoice, type TtsDialect, type TtsVoice } from "@/components/drawer/voice-options";

export type HostedAvatarProfile = {
  displayName: string;
  voiceProvider: "bailian" | "doubao";
  voiceId: TtsVoice;
  voiceDialect: TtsDialect;
  personaId: string | null;
  toolIds: string[];
};

const STORAGE_PREFIX = "openrealtime:hosted-avatar-profile:";

export function defaultHostedAvatarProfile(displayName: string): HostedAvatarProfile {
  return { displayName, voiceProvider: "doubao", voiceId: DEFAULT_TTS_VOICE, voiceDialect: "", personaId: null, toolIds: [] };
}

export function readHostedAvatarProfile(avatarId: string, displayName: string): HostedAvatarProfile {
  const fallback = defaultHostedAvatarProfile(displayName);
  try {
    const value = JSON.parse(window.localStorage.getItem(`${STORAGE_PREFIX}${avatarId}`) ?? "null") as Partial<HostedAvatarProfile> | null;
    if (!value || typeof value !== "object") return fallback;
    return {
      displayName: typeof value.displayName === "string" && value.displayName.trim() ? value.displayName.slice(0, 80) : fallback.displayName,
      voiceProvider: value.voiceProvider === "bailian" ? "bailian" : "doubao",
      voiceId: isTtsVoice(value.voiceId) ? value.voiceId : fallback.voiceId,
      voiceDialect: isTtsDialect(value.voiceDialect) ? value.voiceDialect : "",
      personaId: typeof value.personaId === "string" ? value.personaId : null,
      toolIds: Array.isArray(value.toolIds) ? value.toolIds.filter((id): id is string => typeof id === "string") : [],
    };
  } catch { return fallback; }
}

export function saveHostedAvatarProfile(avatarId: string, profile: HostedAvatarProfile) {
  window.localStorage.setItem(`${STORAGE_PREFIX}${avatarId}`, JSON.stringify(profile));
}
