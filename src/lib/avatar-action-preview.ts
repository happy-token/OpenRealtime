import type { OwnedAvatarActionRecord } from "./avatar-records";
import { BUILTIN_AVATAR_ACTIONS } from "./builtin-avatar-actions";

type ActionPreviewCandidate = Pick<OwnedAvatarActionRecord, "display_name" | "video_url" | "talking_variants">;

export function avatarActionPreviewSources(
  avatarId: string,
  action: ActionPreviewCandidate,
) {
  const normalizedName = action.display_name.normalize("NFKC").trim().toLocaleLowerCase();
  const builtInPreview = BUILTIN_AVATAR_ACTIONS.find((candidate) => (
    candidate.avatarId === avatarId
    && candidate.name.normalize("NFKC").trim().toLocaleLowerCase() === normalizedName
  ))?.videoUrl;
  const talkingPreviews = action.talking_variants
    ?.filter((variant) => !variant.deleted_at && variant.video_url)
    .map((variant) => variant.video_url) ?? [];

  return [...new Set([action.video_url, builtInPreview, ...talkingPreviews]
    .filter((source): source is string => Boolean(source)))];
}
