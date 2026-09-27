import type { OwnedAvatarRecord } from "./avatar-records";

export const ROLE_PRESENTATION_MODES = ["conversation", "motion", "offline", "lip-sync", "realtime"] as const;

export type RolePresentationMode = (typeof ROLE_PRESENTATION_MODES)[number];

export const ROLE_VOICE_DIALECTS = ["", "anhui", "cantonese", "dongbei", "henan", "hunan", "shaanxi", "shandong", "sichuan"] as const;
export type RoleVoiceDialect = (typeof ROLE_VOICE_DIALECTS)[number];

export type RoleDefaultSelections = Partial<Record<"motion" | "offline" | "lip-sync", {
  action_id: string;
  talking_variant_id?: string;
}>> & { realtime?: { avatar_id: string } };

export interface RoleRecord {
  role_id: string;
  display_name: string;
  avatar_id: string | null;
  avatar_image_url: string | null;
  persona_id: string | null;
  persona_name: string | null;
  voice_provider: "bailian" | "doubao";
  voice_id: string;
  voice_dialect?: RoleVoiceDialect;
  asr_provider?: "doubao" | "dashscope" | null;
  llm_provider?: "deepseek" | "openai" | null;
  enabled_modes: RolePresentationMode[];
  default_mode: RolePresentationMode;
  default_selections?: RoleDefaultSelections;
  memory_enabled: boolean;
  model_id?: string | null;
  tool_ids: string[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export const ROLE_MODE_LABELS: Record<RolePresentationMode, string> = {
  conversation: "对话",
  motion: "动作视频",
  offline: "离线数字人",
  "lip-sync": "离线加口型",
  realtime: "实时数字人",
};

export function isRolePresentationMode(value: unknown): value is RolePresentationMode {
  return typeof value === "string" && ROLE_PRESENTATION_MODES.includes(value as RolePresentationMode);
}

export function isRoleVoiceDialect(value: unknown): value is RoleVoiceDialect {
  return typeof value === "string" && ROLE_VOICE_DIALECTS.includes(value as RoleVoiceDialect);
}

export function isRoleRecordId(value: unknown): value is string {
  return value === "default-assistant"
    || (typeof value === "string" && /^role-[A-Za-z0-9-]{3,120}$/.test(value));
}

export function roleModesForAvatar(avatar: OwnedAvatarRecord | null): RolePresentationMode[] {
  if (!avatar || avatar.deleted_at) return ["conversation"];
  const actions = avatar.actions.filter((action) => !action.deleted_at && action.video_url);
  const modes: RolePresentationMode[] = ["conversation"];
  if (actions.some((action) => action.talking_variants?.some((variant) => variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url))) {
    modes.push("offline");
  }
  if (actions.length) {
    modes.push("lip-sync");
  }
  if (avatar.realtime_binding?.state === "accepted") modes.push("realtime");
  return modes;
}

export function enabledRoleModesForAvatar(
  requested: readonly RolePresentationMode[],
  avatar: OwnedAvatarRecord | null,
): RolePresentationMode[] {
  const available = new Set(roleModesForAvatar(avatar));
  // Hosted realtime avatars are configured independently of the offline avatar.
  if (requested.includes("realtime")) available.add("realtime");
  const enabled = ROLE_PRESENTATION_MODES.filter((mode) => requested.includes(mode) && available.has(mode));
  return enabled.length ? enabled : ["conversation"];
}

export function preferredRoleMode(modes: readonly RolePresentationMode[]): RolePresentationMode {
  if (modes.includes("offline")) return "offline";
  if (modes.includes("realtime")) return "realtime";
  if (modes.includes("lip-sync")) return "lip-sync";
  if (modes.includes("motion")) return "motion";
  return "conversation";
}

export function roleDetailDisplayMode(
  requested: RolePresentationMode,
  lipSyncReady: boolean,
  offlineReady: boolean,
): RolePresentationMode {
  if (requested === "realtime" || (requested === "lip-sync" && !lipSyncReady)) {
    return offlineReady ? "offline" : "conversation";
  }
  return requested;
}

export function isRoleDefaultSelections(value: unknown): value is RoleDefaultSelections {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entries = Object.entries(value);
  return entries.every(([mode, selection]) => {
    if (mode === "realtime") {
      if (!selection || typeof selection !== "object" || Array.isArray(selection)) return false;
      const item = selection as Record<string, unknown>;
      return Object.keys(item).length === 1 && typeof item.avatar_id === "string"
        && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(item.avatar_id);
    }
    if (mode !== "motion" && mode !== "offline" && mode !== "lip-sync") return false;
    if (!selection || typeof selection !== "object" || Array.isArray(selection)) return false;
    const item = selection as Record<string, unknown>;
    return Object.keys(item).every((key) => key === "action_id" || key === "talking_variant_id")
      && typeof item.action_id === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/.test(item.action_id)
      && (item.talking_variant_id === undefined || (typeof item.talking_variant_id === "string"
        && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/.test(item.talking_variant_id)));
  });
}

export function resolveRoleDefaultSelection(
  avatar: OwnedAvatarRecord | null,
  mode: RolePresentationMode,
  preferred?: { action_id: string; talking_variant_id?: string },
) {
  if (!avatar || mode === "conversation" || mode === "realtime") return null;
  const actions = avatar.actions.filter((action) => !action.deleted_at && action.video_url);
  const available = mode === "offline" ? actions.filter((action) => action.talking_variants?.some((variant) => (
    variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url
  ))) : actions;
  const action = available.find((item) => item.avatar_action_id === preferred?.action_id) ?? available[0];
  if (!action) return null;
  if (mode !== "offline") return { action_id: action.avatar_action_id };
  const variants = action.talking_variants?.filter((variant) => (
    variant.method === "lipforcing" && !variant.deleted_at && variant.video_url && variant.source_video_url === action.video_url
  )) ?? [];
  const variant = variants.find((item) => item.id === preferred?.talking_variant_id) ?? variants[0];
  return variant ? { action_id: action.avatar_action_id, talking_variant_id: variant.id } : null;
}
