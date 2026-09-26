import type { OwnedAvatarActionRecord } from "./avatar-records";

type GeneratedActionCandidate = Pick<OwnedAvatarActionRecord, "display_name" | "video_url" | "deleted_at">;

/** A named action only counts as generated after it has a usable, non-deleted video. */
export function hasGeneratedAvatarAction(
  actions: readonly GeneratedActionCandidate[],
  displayName: string,
) {
  const normalizedName = displayName.trim();
  if (!normalizedName) return false;

  return actions.some((action) => (
    !action.deleted_at
    && Boolean(action.video_url)
    && action.display_name.trim() === normalizedName
  ));
}
