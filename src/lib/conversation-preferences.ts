export const CONVERSATION_PREFERENCES_KEY = "openrealtime-conversation-preferences";

export type ConversationPreferences = {
  volume: number;
  allowBargeIn: boolean;
  noiseSuppression: boolean;
};

export const DEFAULT_CONVERSATION_PREFERENCES: ConversationPreferences = {
  volume: 80,
  allowBargeIn: true,
  noiseSuppression: true,
};

export function readConversationPreferences(): ConversationPreferences {
  if (typeof window === "undefined") return DEFAULT_CONVERSATION_PREFERENCES;
  try {
    const value = JSON.parse(window.localStorage.getItem(CONVERSATION_PREFERENCES_KEY) ?? "null") as Partial<ConversationPreferences> | null;
    return {
      volume: typeof value?.volume === "number" && Number.isFinite(value.volume) && value.volume >= 0 && value.volume <= 100 ? value.volume : 80,
      allowBargeIn: typeof value?.allowBargeIn === "boolean" ? value.allowBargeIn : true,
      noiseSuppression: typeof value?.noiseSuppression === "boolean" ? value.noiseSuppression : true,
    };
  } catch {
    return DEFAULT_CONVERSATION_PREFERENCES;
  }
}

export function writeConversationPreferences(value: ConversationPreferences) {
  window.localStorage.setItem(CONVERSATION_PREFERENCES_KEY, JSON.stringify(value));
}
