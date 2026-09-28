import type { OwnedAvatarRecord } from "./avatar-records";
import type { RoleDefaultSelections } from "./role-records";

export function validRoleAssetSelection(avatar: OwnedAvatarRecord | null, actionId: string | null, variantId: string | null) {
  const action = !avatar?.deleted_at ? avatar?.actions.find(item => item.avatar_action_id === actionId && !item.deleted_at && item.video_url) : null;
  const variant = action?.talking_variants?.find(item => item.id === variantId && !item.deleted_at && item.video_url && item.method === "lipforcing" && item.source_video_url === action.video_url);
  return { actionId: action?.avatar_action_id ?? null, variantId: variant?.id ?? null };
}

export function cleanRoleAssetDefaults(avatar: OwnedAvatarRecord | null, selections: RoleDefaultSelections | undefined): RoleDefaultSelections {
  const next: RoleDefaultSelections = { ...(selections?.realtime ? { realtime: selections.realtime } : {}) };
  for (const mode of ["motion", "lip-sync", "offline"] as const) {
    const selection = selections?.[mode];
    if (!selection) continue;
    const valid = validRoleAssetSelection(avatar, selection.action_id, selection.talking_variant_id ?? null);
    if (valid.actionId && (mode !== "offline" || valid.variantId)) next[mode] = {
      action_id: valid.actionId, ...(mode === "offline" && valid.variantId ? { talking_variant_id: valid.variantId } : {}),
    };
  }
  return next;
}
